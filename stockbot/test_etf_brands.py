import unittest
from unittest.mock import Mock

from stockbot.etf_brands import BRANDS, brand_query, listing_brand
from stockbot.stock_quotes import StockService
from stockbot.portfolio import PortfolioService


def output(code):
    return dict(stck_shrn_iscd=code,stck_prpr='100')


class ETFBrandTests(unittest.TestCase):
    def test_all_brands_are_bidirectional_with_or_without_spaces(self):
        for brand, korean, *extra in BRANDS:
            for source, query in [(brand+' 200',korean+'200'),(korean+' 200',brand.lower()+'200')]:
                with self.subTest(source=source,query=query):
                    quote, us=Mock(side_effect=output),Mock()
                    service=StockService(codes_loader=lambda:{source:'KRX:000001'},quote_loader=quote,
                                         us_loader=us,basic_loader=lambda c:{})
                    self.assertIn('✔️ 현재가:',service.reply(query))
                    quote.assert_called_once_with('000001');us.assert_not_called()

    def test_exact_etf_beats_variants_and_multiple_candidates_show_choices(self):
        quote=Mock(side_effect=output)
        service=StockService(codes_loader=lambda:{'KODEX 200':'KRX:069500','KODEX 200선물인버스2X':'KRX:252670'},
                             quote_loader=quote,basic_loader=lambda c:{})
        service.reply('코덱스200');quote.assert_called_once_with('069500')
        quote.reset_mock()
        text=service.reply('코덱스2')
        self.assertIn('여러 종목',text);self.assertIn('069500',text);self.assertIn('252670',text)
        quote.assert_not_called()

    def test_compact_six_character_brand_name_is_not_treated_as_a_code(self):
        quote=Mock(side_effect=output)
        service=StockService(codes_loader=lambda:{'ACE 200':'KRX:000001'},quote_loader=quote,basic_loader=lambda c:{})
        service.reply('ACE200');quote.assert_called_once_with('000001')

    def test_company_prefixes_and_us_tickers_are_not_globally_replaced(self):
        for name in ('솔브레인','원익IPS','타임기술'):
            self.assertIsNone(listing_brand(name))
        self.assertIsNone(brand_query('SOL'))
        quote=Mock(side_effect=output)
        service=StockService(codes_loader=lambda:{'솔브레인':'KRX:000001','SOL 반도체':'KRX:000002'},
                             quote_loader=quote,basic_loader=lambda c:{})
        service.reply('솔브');quote.assert_called_once_with('000001')

    def test_daishin_alternate_spelling_and_exact_name_lookup(self):
        service=StockService(codes_loader=lambda:{'DAISHIN 가상ETF':'KRX:000001'})
        self.assertEqual(service.ticker_for_name('대신가상ETF','KRW'),'000001')
        self.assertEqual(service.ticker_for_name('dashin 가상ETF','KRW'),'000001')
        self.assertEqual(service.ticker_for_name('대신가상','KRW'),'')

    def test_portfolio_and_realized_use_same_bilingual_search(self):
        data=dict(schema_version=1,generated_at='2026-10-29',
                  holdings=[dict(name='KODEX 200',ticker='KRX:069500',currency='KRW',average='100')],
                  realized=[dict(name='KODEX 200',return_pct='1',last_trade_date='03.27.')])
        service=PortfolioService(lambda:data)
        self.assertIn('[KODEX 200]',service.reply('평단','코덱스200'))
        self.assertIn('KODEX 200: ▲1.00%',service.reply('실현','코덱스200'))


if __name__=='__main__':
    unittest.main()
