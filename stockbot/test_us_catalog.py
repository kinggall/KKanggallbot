import re
import unittest
from unittest.mock import Mock

from stockbot.us_catalog import find_names, get_record, indexes, english_name
from stockbot.us_catalog_data import PDF_ROWS, SP500_COUNT, RECORDS, SOURCES
from stockbot.stock_quotes import StockService
from stockbot.security_names import USSecurityNames


def quote(symbol):
    return dict(exchange='NAS',rsym='DNAS'+symbol,curr='USD',last='100',base='90')


class USCatalogTests(unittest.TestCase):
    def test_every_sp500_korean_name_reaches_us_quote_or_explicit_choices(self):
        us=Mock(side_effect=quote)
        service=StockService(codes_loader=lambda:{},us_loader=us)
        for record in indexes()[0].values():
            if not record[4]:
                continue
            symbol=record[0]
            name=next(n for n in record[2] if re.search('[가-힣]',n))
            with self.subTest(symbol=symbol,name=name):
                us.reset_mock()
                text=service.reply(name)
                self.assertTrue('✔️ 현재가:' in text or '여러 종목' in text,text)
                if '✔️ 현재가:' in text and us.called:
                    self.assertEqual(us.call_args.args[0],symbol)

    def test_catalog_covers_all_sp500_components_and_490_pdf_rows(self):
        self.assertEqual(PDF_ROWS,490)
        self.assertGreaterEqual(len(indexes()[0]),6000)
        components=[r for r in indexes()[0].values() if r[4]]
        self.assertEqual(len(components),SP500_COUNT)
        self.assertGreaterEqual(SP500_COUNT,500)
        for symbol,english,korean,venues,sp500 in components:
            with self.subTest(symbol=symbol):
                self.assertTrue(any(re.search('[가-힣]',name) for name in korean))
                for name in korean:
                    self.assertIn(symbol,find_names(name,exact_only=True))
        self.assertEqual(len(SOURCES),4)
        self.assertTrue(all(re.fullmatch('[a-f0-9]{64}',digest) for url,digest in SOURCES))

    def test_requested_korean_aliases_use_us_quotes_not_domestic_etf_search(self):
        cases=[('스페이스X','SPCX'),('스엑','SPCX'),('spaceX','SPCX'),
               ('하닉adr','SKHY'),('하이닉스(ADR)','SKHY'),('하이닉스 ADR','SKHY'),
               ('오라클','ORCL'),('Oracle','ORCL'),('코어위브','CRWV'),('CoreWeave','CRWV'),
               ('마이크론 테크놀로지','MU'),('Micron','MU'),
               ('코스트코 홀세일','COST'),('쓰리엠','MMM'),('브라운 포맨 B','BF/B')]
        for keyword,symbol in cases:
            with self.subTest(keyword=keyword):
                us=Mock(side_effect=quote); domestic=Mock(); listing=Mock(side_effect=AssertionError('not domestic'))
                service=StockService(us_loader=us,quote_loader=domestic,codes_loader=listing)
                self.assertIn('✔️ 현재가:',service.reply(keyword))
                us.assert_called_once_with(symbol); domestic.assert_not_called(); listing.assert_not_called()

    def test_micron_shows_mu_first_and_domestic_hana_without_fetching_quotes(self):
        us,kr=Mock(),Mock()
        service=StockService(codes_loader=lambda:{'하나마이크론':'KOSDAQ:067310'},us_loader=us,quote_loader=kr)
        text=service.reply('마이크론')
        self.assertIn('MU · 미국',text);self.assertIn('067310 · 국내',text)
        self.assertLess(text.index('MU'),text.index('하나마이크론'))
        us.assert_not_called();kr.assert_not_called()

    def test_real_ticker_wins_over_a_company_name_abbreviation(self):
        us=Mock(side_effect=quote)
        service=StockService(us_loader=us)
        self.assertIn('✔️ 현재가:',service.reply('HP'))
        us.assert_called_once_with('HP')
        us.reset_mock()
        self.assertIn('✔️ 현재가:',service.reply('에이치피'))
        us.assert_called_once_with('HPQ')

    def test_class_symbol_merge_preserves_index_membership_names_and_venue(self):
        for symbol in ('BRK/B','BF/B'):
            record=get_record(symbol)
            self.assertTrue(record[2]);self.assertTrue(record[3]);self.assertTrue(record[4])

    def test_known_full_names_are_local_and_need_no_public_directory_request(self):
        from unittest.mock import patch
        with patch('stockbot.security_names.requests.get') as get:
            names=USSecurityNames()
            for symbol in ('SPCX','SKHY','ORCL','CRWV'):
                self.assertEqual(names(symbol),english_name(symbol))
                self.assertNotEqual(names(symbol),'종목명 미확인')
            get.assert_not_called()

    def test_historical_only_pdf_entries_do_not_become_live_ticker_aliases(self):
        us=Mock()
        service=StockService(codes_loader=lambda:{},us_loader=us)
        self.assertIn('2020년 자료',service.reply('아비오메드'))
        us.assert_not_called()


if __name__=='__main__':
    unittest.main()
