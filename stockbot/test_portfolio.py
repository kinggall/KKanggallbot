import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from stockbot.portfolio import PortfolioService
from stockbot import stock_commands, stock_quotes, us_quotes


def snapshot():
    return {'schema_version': 1, 'generated_at': '2026-10-29T20:00:00+09:00',
            'holdings_collected_at': '2026-10-29T19:00:00+09:00',
            'holdings': [{'name': '가상회사', 'ticker': 'KRX:000001', 'account': '가상계좌',
                          'currency': 'KRW', 'quantity': '2', 'average': '1234.5',
                          'unrealized_profit': '100', 'return_pct': '4.05'},
                         {'name': '가상미국', 'ticker': 'NAS:FAKE', 'currency': 'USD',
                          'quantity': '0.5', 'average': '10.12', 'return_pct': None}],
            'realized': [{'name': '가상회사', 'currency': 'KRW', 'realized_profit': '-500',
                          'return_pct': '-2.3', 'period': {'label': '가상기간'},
                          'display_source': 'Domino'}]}


class PortfolioTests(unittest.TestCase):
    def test_simplified_layout_only_shows_requested_values_and_dates(self):
        data = snapshot()
        data['quotes_read_at'] = '2026-10-29T16:00:00Z'
        data['holdings'][0].update(return_pct='-4.92257686628113218442957671', average_at='2026-10-28T22:01:19Z')
        service = PortfolioService(lambda: data)
        self.assertEqual(service.reply('평단', '가상회사'), '[평균 매입가]\n· 가상회사: 1,234.5원\n\n갱신 일자: 2026-10-29')
        self.assertEqual(service.reply('수익률', '가상회사'), '[보유 수익률]\n· 가상회사: -4.92%\n\n갱신 일자: 2026-10-29\n시세 기준: 2026-10-30')
        self.assertEqual(service.reply('실현', '가상회사'), '[실현 수익률]\n· 가상회사: -2.30%\n\n갱신 일자: 2026-10-29')
        for command in ('평단', '수익률', '실현'):
            text = service.reply(command, '가상회사')
            for hidden in ('가상계좌', '평가손익', '실현손익', '자료 갱신', '보유 수집', '가상기간', '+00:00'):
                self.assertNotIn(hidden, text)

    def test_commands_use_exported_values_and_timestamp(self):
        s = PortfolioService(snapshot)
        self.assertIn('가상회사(000001)', s.reply('보유'))
        self.assertIn('1,234.5원', s.reply('평단', '가상회사'))
        self.assertIn('10.12 USD', s.reply('평단', 'FAKE'))
        self.assertIn('4.05%', s.reply('수익률', '가상회사'))
        self.assertIn('미확인', s.reply('수익률', 'FAKE'))
        self.assertIn('!실현 가상회사', s.reply('실현'))
        text = s.reply('실현', '가상회사')
        for expected in ('-2.30%', '갱신 일자: 2026-10-29'):
            self.assertIn(expected, text)

    def test_no_aggregation_of_different_accounts_or_periods(self):
        data = snapshot()
        data['holdings'].append(dict(data['holdings'][0], account='다른계좌', average='99'))
        text = PortfolioService(lambda: data).reply('평단', '가상회사')
        self.assertIn('1,234.5원', text)
        self.assertIn('99원', text)

    def test_usage_missing_data_ambiguity_and_errors(self):
        loader = Mock(side_effect=RuntimeError('secret-token'))
        s = PortfolioService(loader)
        self.assertIn('사용법', s.reply('평단'))
        loader.assert_not_called()
        self.assertNotIn('secret-token', s.reply('보유'))
        s = PortfolioService(snapshot)
        self.assertIn('없습니다', s.reply('평단', '없는회사'))
        self.assertIn('정확한', s.reply('평단', '가상'))

    def test_cache_expires_and_does_not_serve_stale_on_failure(self):
        clock = [0]
        loader = Mock(side_effect=[snapshot(), RuntimeError('private')])
        s = PortfolioService(loader, lambda: clock[0])
        s.reply('보유'); clock[0] = 29; s.reply('보유')
        self.assertEqual(loader.call_count, 1)
        clock[0] = 31
        self.assertIn('읽지 못했습니다', s.reply('보유'))

    def test_routing_all_rooms_without_real_chat_send(self):
        class Inline:
            def submit(self, fn): fn()
        for command in ('!보유', '!평단 가상회사', '!수익률 가상회사', '!실현', '!실현 가상회사'):
            with patch.object(stock_commands, 'EXECUTOR', Inline()), patch.object(stock_commands.PORTFOLIO, 'reply', return_value='fixture') as reply, patch.object(stock_commands.requests, 'post') as post:
                self.assertEqual(stock_commands.handle(command, 'any-room', 'http://local/reply')[1], 200)
                self.assertEqual(post.call_args.kwargs['json']['room'], 'any-room')
                reply.assert_called_once()


class QuoteExtensionTests(unittest.TestCase):
    def test_quote_layout_uses_exchange_names_without_extra_notices(self):
        when = datetime(2026, 10, 29, 21, tzinfo=stock_quotes.KST)
        payload = {'stck_shrn_iscd':'000001','stck_prpr':'100'}
        domestic = stock_quotes.format_quote(stock_quotes.parse_quote(payload, '000001', '가상', when))
        self.assertIn('조회 · 장외\n출처:', domestic)
        for exchange, name in us_quotes.EXCHANGE_NAMES.items():
            output = dict(exchange=exchange, rsym='D'+exchange+'FAKE', curr='USD', last='100')
            text = us_quotes.format_us(output, 'FAKE', when)
            self.assertIn('출처: 한국투자증권 · 미국 ' + name, text)
            self.assertNotIn('※', text)
            self.assertNotIn('최근 시세', text)
        self.assertNotIn('※', domestic)
        self.assertNotIn('최근 시세', domestic)

    def test_utf8_drive_plain_text_is_not_decoded_as_latin1(self):
        import json
        from stockbot.portfolio import load_snapshot
        response = Mock()
        response.content = json.dumps(snapshot(), ensure_ascii=False).encode('utf-8')
        with patch('scripts.sync_drive_data.Drive') as drive:
            drive.return_value.call.return_value = response
            self.assertEqual(load_snapshot()['holdings'][0]['name'], '가상회사')

    def test_domestic_request_is_integrated(self):
        s = stock_quotes.StockService()
        kis = Mock(); kis.DOMESTIC = ('path', 'tr')
        s.client = Mock()
        with patch.object(s, '_modules', return_value=(kis, None)):
            s._load_quote('000001')
        self.assertEqual(s.client.query.call_args.args[1]['FID_COND_MRKT_DIV_CODE'], 'UN')

    def test_session_boundaries_and_weekend(self):
        base = datetime(2026, 10, 29, tzinfo=stock_quotes.KST)
        for hour, minute, expected in [(8,0,'NXT 프리'),(8,50,'장외'),(9,0,'정규장'),(15,30,'장외'),(16,0,'NXT 애프터'),(20,0,'장외')]:
            self.assertIn(expected, stock_quotes.domestic_session(base.replace(hour=hour,minute=minute)))
        self.assertIn('장외', stock_quotes.domestic_session(base + timedelta(days=2,hours=10)))

    def test_us_ticker_precedes_domestic_partial_search_and_caches(self):
        output = {'exchange':'AMS','rsym':'DAMSDRAM','curr':'USD','last':'20.12','base':'20','tvol':'5','tamt':'100.6'}
        loader = Mock(return_value=output)
        catalog = Mock(side_effect=AssertionError('no domestic lookup'))
        s = stock_quotes.StockService(codes_loader=catalog, us_loader=loader)
        first = s.reply('DRAM')
        self.assertIn('20.12 USD', first)
        self.assertIn('DRAM', first)
        self.assertEqual(s.reply('dram'), first)
        loader.assert_called_once_with('DRAM'); catalog.assert_not_called()

    def test_overseas_endpoint_uses_domino_allowed_path_and_validates_symbol(self):
        spec = '/uapi/overseas-price/v1/quotations/price-detail'
        self.assertEqual(us_quotes.overseas_spec(spec), spec)
        client = Mock()
        client.query.side_effect = [{}, {}, {'rsym':'DAMSDRAM','curr':'USD','last':'20'}]
        self.assertEqual(us_quotes.load_us(client,spec,'DRAM')['exchange'],'AMS')
        self.assertEqual([c.args[1]['EXCD'] for c in client.query.call_args_list],['NAS','NYS','AMS'])
        with self.assertRaises(stock_quotes.QuoteError):
            us_quotes.overseas_spec('unknown')
        with self.assertRaises(stock_quotes.QuoteError):
            us_quotes.format_us({'exchange':'NAS','rsym':'DNASOTHER','last':'1'}, 'DRAM', datetime.now(stock_quotes.KST))

    def test_us_dst_regular_session(self):
        for when in (datetime(2026,7,1,22,30,tzinfo=stock_quotes.KST), datetime(2026,12,1,23,30,tzinfo=stock_quotes.KST)):
            self.assertEqual(us_quotes.us_session(when),'정규장')
            with patch.object(us_quotes, 'ZoneInfo', side_effect=us_quotes.ZoneInfoNotFoundError):
                self.assertEqual(us_quotes.us_session(when),'정규장')

    def test_missing_us_symbol_on_first_exchange_does_not_prevent_amex(self):
        endpoint = us_quotes.PATH
        client = Mock()
        client.query.side_effect = [ValueError('provider-private'), {}, {'rsym':'DAMSDRAM','curr':'USD','last':'20'}]
        self.assertEqual(us_quotes.load_us(client, endpoint, 'DRAM')['exchange'], 'AMS')

    def test_installed_domino_string_endpoint_is_passed_without_rewriting(self):
        from types import SimpleNamespace
        endpoint = us_quotes.PATH
        def query(path, params):
            if path != endpoint:
                raise ValueError('not allowed')
            exchange, symbol = params['EXCD'], params['SYMB']
            if symbol == 'DRAM' and exchange != 'AMS':
                return {}
            return {'rsym':'D'+exchange+symbol, 'curr':'USD', 'last':'10', 'base':'9'}
        service = stock_quotes.StockService()
        service.client = Mock(); service.client.query.side_effect = query
        kis = SimpleNamespace(DOMESTIC='/uapi/domestic-stock/v1/quotations/inquire-price', OVERSEAS=endpoint)
        with patch.object(service, '_modules', return_value=(kis,None)):
            for symbol in ('DRAM', 'AAPL'):
                self.assertIn('✔️ 현재가:', service.reply(symbol))
        self.assertTrue(all(c.args[0] == endpoint for c in service.client.query.call_args_list))

    def test_us_non_dollar_data_is_rejected(self):
        with self.assertRaises(stock_quotes.QuoteError):
            us_quotes.format_us({'exchange':'NAS','rsym':'DNASAAPL','curr':'KRW','last':'10'}, 'AAPL', datetime.now(stock_quotes.KST))


if __name__ == '__main__':
    unittest.main()
