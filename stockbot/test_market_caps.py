from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
import unittest

from stockbot import stock_commands
from stockbot.market_caps import MARKETS, KISMarketCapLoader, MarketCaps, parse_snapshot, percent_text
from stockbot.market_data import MarketDataError
from stockbot.night_futures import ENDPOINTS, MARKET_CAP
from stockbot.stock_quotes import KST

NOW = datetime(2026, 11, 17, 9, 55, 43, tzinfo=KST)


def payload():
    rows = []
    for i in range(1, 10):
        rows.append({'data_rank': str(i), 'mksc_shrn_iscd': f'{i:06d}',
                     'hts_kor_isnm': '가상기업우' if i == 3 else f'시총종목{i}',
                     'stck_avls': str(100000 - i), 'prdy_ctrt': str(i / 10),
                     'prdy_vrss_sign': '2' if i % 2 else '5'})
    return {'rt_cd': '0', 'output': rows}


class CapTests(unittest.TestCase):
    def test_ranking_is_by_official_market_cap_rank_not_response_order_or_change_percent(self):
        data = payload()
        data['output'].reverse()
        snapshot = parse_snapshot(data, NOW)
        self.assertEqual([r.rank for r in snapshot.rows], list(range(1, 9)))
        self.assertEqual(len(snapshot.rows), 8)
        self.assertEqual(snapshot.rows[2].name, '가상기업우')
        self.assertEqual(snapshot.rows[1].percent, Decimal('-0.2'))

    def test_missing_and_duplicate_top_ranks_are_never_padded_or_renumbered(self):
        for variant in ('missing', 'rank_duplicate', 'code_duplicate', 'cap_missing'):
            data = payload()
            if variant == 'missing':
                del data['output'][2]
            elif variant == 'rank_duplicate':
                data['output'][1]['data_rank'] = '1'
            elif variant == 'code_duplicate':
                data['output'][1]['mksc_shrn_iscd'] = '000001'
            else:
                data['output'][1]['stck_avls'] = ''
            with self.subTest(variant=variant), self.assertRaises(MarketDataError):
                parse_snapshot(data, NOW)

    def test_missing_percent_is_not_zero_and_limit_up_down_signs_are_honored(self):
        data = payload()
        data['output'][0].update(prdy_ctrt='', prdy_vrss_sign='2')
        data['output'][1].update(prdy_ctrt='0', prdy_vrss_sign='3')
        data['output'][2].update(prdy_ctrt='30', prdy_vrss_sign='1')
        data['output'][3].update(prdy_ctrt='30', prdy_vrss_sign='4')
        rows = parse_snapshot(data, NOW).rows
        self.assertEqual([percent_text(r.percent) for r in rows[:4]],
                         ['등락률 미확인', '0.00%', '🔺30.00%', '▼30.00%'])

    def test_loader_uses_official_exchange_filters_and_includes_preferred_shares(self):
        adapter = Mock()
        loader = KISMarketCapLoader(adapter, now=lambda: NOW)
        for market, code in zip(MARKETS, ('0001', '1001')):
            with patch('stockbot.market_caps.query', return_value=payload()) as query:
                snapshot = loader(market)
            client, path, params = query.call_args.args
            self.assertIs(client, adapter.client_instance.return_value)
            self.assertEqual(path, '/uapi/domestic-stock/v1/ranking/market-cap')
            self.assertEqual(ENDPOINTS[MARKET_CAP], 'FHPST01740000')
            self.assertEqual(params['fid_input_iscd'], code)
            self.assertEqual(params['fid_cond_scr_div_code'], '20174')
            self.assertEqual(params['fid_cond_mrkt_div_code'], 'J')
            self.assertEqual(params['fid_div_cls_code'], '0')
            self.assertTrue(all(params[k] == '' for k in ('fid_input_price_1', 'fid_input_price_2', 'fid_vol_cnt')))
            self.assertEqual(len(snapshot.rows), 8)

    def test_layout_has_two_distinct_markets_eight_rows_each_and_kst_query_timestamp(self):
        snapshot = parse_snapshot(payload(), NOW)
        text = MarketCaps(lambda _: snapshot).reply()
        self.assertTrue(text.startswith('🔥 한국시장 시총 Top 8 🔥\n🕰️ 조회: 11-17(화) 9시 55분 43초'))
        self.assertIn('🔴 << 코스피 Top 8 >> 🔴', text)
        self.assertIn('🔵 << 코스닥 Top 8 >> 🔵', text)
        self.assertEqual(text.count('1️⃣ '), 2)
        self.assertEqual(text.count('8️⃣ '), 2)
        self.assertNotIn('시총종목9', text)
        self.assertIn('2️⃣ 시총종목2 (▼0.20%)', text)
        self.assertTrue(text.endswith('출처: 한국투자증권'))

    def test_one_market_can_fail_without_erasing_the_other_or_exposing_errors(self):
        def load(market):
            if market[0] == 'kosdaq':
                raise RuntimeError('PRIVATE_AUTH_VALUE')
            return parse_snapshot(payload(), NOW)
        text = MarketCaps(load).reply()
        self.assertIn('8️⃣ 시총종목8', text)
        self.assertIn('🔵 << 코스닥 Top 8 >> 🔵\n\n조회 불가', text)
        self.assertNotIn('PRIVATE_AUTH_VALUE', text)

    def test_expired_success_is_not_served_as_current_after_loader_failure(self):
        tick = [0]
        load = Mock(side_effect=[parse_snapshot(payload(), NOW), RuntimeError('offline')])
        service = MarketCaps(load, monotonic=lambda: tick[0])
        self.assertIsNotNone(service.load(MARKETS[0]))
        tick[0] = 14
        self.assertIsNotNone(service.load(MARKETS[0]))
        self.assertEqual(load.call_count, 1)
        tick[0] = 16
        self.assertIsNone(service.load(MARKETS[0]))

    def test_command_routes_to_original_room_without_portfolio_or_individual_quote_calls(self):
        class Inline:
            def submit(self, fn): fn()
        with patch.object(stock_commands, 'EXECUTOR', Inline()), \
                patch.object(stock_commands.CAPS, 'reply', return_value='fixture ranking') as caps, \
                patch.object(stock_commands.PORTFOLIO, 'reply') as portfolio, \
                patch.object(stock_commands.SERVICE, 'reply') as quote, \
                patch.object(stock_commands.requests, 'post') as send:
            self.assertEqual(stock_commands.handle('!시총', 'room', 'http://local/reply')[1], 200)
            caps.assert_called_once()
            self.assertEqual(send.call_args.kwargs['json'], {'type': 'text', 'room': 'room', 'data': 'fixture ranking'})
            portfolio.assert_not_called()
            quote.assert_not_called()
            for command in ('시총', '!시총 삼성전자', '!시총아님'):
                self.assertIsNone(stock_commands.handle(command, 'room', 'http://local/reply'))
            self.assertEqual(caps.call_count, 1)

    def test_help_stays_in_the_stock_menu_only(self):
        import bot
        self.assertIn('!시총', stock_commands.INVESTMENT_HELP)
        for value in bot.COMMANDS.values():
            self.assertNotIn('!시총', value)


if __name__ == '__main__':
    unittest.main()
