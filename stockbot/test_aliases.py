import unittest
from unittest.mock import Mock

from stockbot.stock_quotes import StockService, USAGE
from stockbot.aliases import lookup, us_symbol


def domestic(code):
    return dict(stck_shrn_iscd=code, stck_prpr='100', stck_prdy_clpr='90')


def overseas(symbol):
    return dict(exchange='NYS' if symbol.startswith('BRK/') else 'NAS',
                rsym=('DNYS' if symbol.startswith('BRK/') else 'DNAS') + symbol,
                curr='USD', last='100', base='90')


class StockAliasTests(unittest.TestCase):
    def test_ticker_names_do_not_fetch_quotes(self):
        quote=Mock()
        service=StockService(codes_loader=lambda:{'가상회사':'KRX:000001'},quote_loader=quote)
        self.assertEqual(service.names_for_ticker('000001'),['가상회사'])
        self.assertIn('애플',service.names_for_ticker('AAPL'))
        self.assertEqual(service.names_for_ticker('없는 이름'),[])
        quote.assert_not_called()

    def test_domestic_aliases_resolve_without_listing_lookup(self):
        for alias, code, name in [('삼전','005930','삼성전자'), ('두에빌','034020','두산에너빌리티'),
                                  ('현차','005380','현대차'), ('현대차','005380','현대차'),
                                  ('현대자동차','005380','현대차')]:
            with self.subTest(alias=alias):
                quote = Mock(side_effect=domestic)
                master = Mock(side_effect=AssertionError('no catalog required'))
                service = StockService(codes_loader=master, quote_loader=quote, basic_loader=lambda c:{})
                self.assertIn(name + ' 주가', service.reply(alias))
                quote.assert_called_once_with(code); master.assert_not_called()

    def test_us_korean_names_precede_domestic_etf_partial_matches(self):
        cases = [('애플','AAPL'),('구글','GOOGL'),('알파벳a','GOOGL'),('알파벳 A','GOOGL'),
                 ('알파벳c','GOOG'),('버크셔','BRK/B'),('버크셔 해서웨이','BRK/B'),
                 ('버크셔a','BRK/A'),('버크셔b','BRK/B')]
        for keyword, symbol in cases:
            with self.subTest(keyword=keyword):
                master = Mock(return_value={'RISE 버크셔포트폴리오TOP10':'KRX:475350'})
                us = Mock(side_effect=overseas)
                kr = Mock(side_effect=AssertionError('not domestic'))
                service = StockService(codes_loader=master, us_loader=us, quote_loader=kr)
                self.assertIn('✔️ 현재가:', service.reply(keyword))
                us.assert_called_once_with(symbol); master.assert_not_called(); kr.assert_not_called()

    def test_prefix_single_candidate_auto_queries_and_uses_real_name(self):
        quote = Mock(side_effect=domestic)
        master = {'한온시스템':'KRX:018880', '가상 한온 ETF':'KRX:000001'}
        service = StockService(codes_loader=lambda:master, quote_loader=quote, basic_loader=lambda c:{})
        self.assertIn('한온시스템 주가', service.reply('한온'))
        quote.assert_called_once_with('018880')

    def test_unique_contains_auto_queries_and_exact_match_wins(self):
        quote = Mock(side_effect=domestic)
        service = StockService(codes_loader=lambda:{'가상반도체':'KRX:000001'}, quote_loader=quote, basic_loader=lambda c:{})
        self.assertIn('가상반도체 주가', service.reply('반도체'))
        quote.assert_called_once_with('000001')
        quote.reset_mock()
        service = StockService(codes_loader=lambda:{'가상':'KRX:000001','가상우':'KRX:000002'}, quote_loader=quote, basic_loader=lambda c:{})
        service.reply('가상'); quote.assert_called_once_with('000001')

    def test_multiple_candidates_are_never_selected_arbitrarily(self):
        quote = Mock()
        service = StockService(codes_loader=lambda:{'가상회사':'KRX:000001','가상회사우':'KRX:000002'},quote_loader=quote)
        text = service.reply('가상')
        self.assertTrue(text.startswith('여러 종목이 검색됐습니다.\n종목명·티커로 입력해 주세요.'))
        self.assertIn('· 가상회사 (000001)',text); self.assertIn('· 가상회사우 (000002)',text)
        self.assertNotIn('6자리',text); quote.assert_not_called()

    def test_ticker_spelling_and_alias_share_the_quote_cache(self):
        us = Mock(side_effect=overseas)
        service = StockService(us_loader=us)
        self.assertEqual(service.reply('애플'), service.reply('aapl'))
        us.assert_called_once_with('AAPL')
        for spelling in ('BRK.B','brk-b','BRK/B'):
            self.assertEqual(us_symbol(spelling), 'BRK/B')
        self.assertEqual(lookup('알파벳 Ａ')[1], 'GOOGL')
        self.assertIn('종목명·티커로 입력해 주세요.',USAGE)


if __name__ == '__main__':
    unittest.main()
