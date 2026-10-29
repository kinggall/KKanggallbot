import unittest

from stockbot.portfolio import PortfolioService, arrow_percent, trade_date_text


class RealizedLayoutTests(unittest.TestCase):
    def test_yearless_trade_dates_use_explicit_2026_ledger_year(self):
        for raw, expected in [('03.27.','2026-03-27'),('03.19.','2026-03-19'),
                              ('3. 7.','2026-03-07'),('03/19','2026-03-19'),
                              ('2025-03-19','2025-03-19'),('02.30.','미확인'),(None,'미확인')]:
            with self.subTest(raw=raw):
                self.assertEqual(trade_date_text(raw),expected)
        data=self.snapshot();data['realized'][0]['last_trade_date']='03.27.'
        self.assertIn('최종 거래일 : 2026-03-27',PortfolioService(lambda:data).reply('실현','가상회사'))
    def test_us_realized_krw_profit_is_not_classified_as_korean_listing(self):
        from unittest.mock import Mock
        data=self.snapshot()
        data['realized']=[dict(name=s,currency='KRW',ticker=None) for s in ('KORU','SPCX')]
        names={'KORU':'Public KORU Fund Name','SPCX':'Public SPCX Security Name'}
        service=PortfolioService(lambda:data,name_loader=lambda symbol:names[symbol],ticker_lookup=Mock(return_value=''))
        text=service.reply('실현')
        self.assertIn('KORU(Public KORU Fund Name)',text)
        self.assertIn('SPCX(Public SPCX Security Name)',text)
        self.assertNotIn('코드 미확인',text)
        self.assertTrue(all(r['currency']=='KRW' and r['ticker'] is None for r in data['realized']))

    def test_korean_english_name_stays_domestic_with_verified_numeric_ticker(self):
        from unittest.mock import Mock
        data=self.snapshot();data['realized']=[dict(name='NAVER',currency='KRW')]
        names=Mock(side_effect=AssertionError('must not query US names'))
        service=PortfolioService(lambda:data,name_loader=names,ticker_lookup=lambda name,currency:'035420')
        self.assertIn('NAVER(035420)',service.reply('실현'))
        names.assert_not_called()

    def test_us_holdings_market_is_retained_when_realized_profit_is_krw(self):
        data=self.snapshot()
        data['holdings']=[dict(name='FAKE',ticker='NASDAQ:FAKE',currency='USD')]
        data['realized']=[dict(name='FAKE',currency='KRW')]
        service=PortfolioService(lambda:data,name_loader=lambda symbol:'Public Full Name')
        self.assertIn('FAKE(Public Full Name)',service.reply('실현'))

    def test_realized_list_matches_holdings_layout_and_deduplicates(self):
        data=self.snapshot()
        data['realized'].append(dict(data['realized'][0],account='second-account'))
        data['realized'].append(dict(name='가상 ETF',currency='KRW',ticker='KRX:000002'))
        data['holdings']=[dict(name='가상회사',ticker='KRX:000001',currency='KRW')]
        text=PortfolioService(lambda:data).reply('실현')
        self.assertEqual(text,'[실현 수익률]\n· 가상회사(000001)\n· 가상 ETF(000002)\n\n갱신 일자: 2026-10-29')
        self.assertNotIn('상세',text)
        self.assertNotIn('secret',text)
        self.assertNotIn('▼',text)

    def test_realized_missing_ticker_uses_exact_public_name_lookup(self):
        from unittest.mock import Mock
        data=self.snapshot()
        lookup=Mock(return_value='000003')
        text=PortfolioService(lambda:data,ticker_lookup=lookup).reply('실현')
        self.assertIn('· 가상회사(000003)',text)
        lookup.assert_called_once_with('가상회사','KRW')
        self.assertNotIn('ticker',data['realized'][0])

    def test_ticker_resolves_realized_name_even_when_realized_row_has_no_ticker(self):
        data=self.snapshot()
        service=PortfolioService(lambda:data,symbol_names=lambda ticker:['가상회사'] if ticker=='000001' else [])
        self.assertIn('가상회사: ▼14.34%',service.reply('실현','000001'))
        data['holdings']=[dict(name='가상회사',ticker='NASDAQ:FAKE')]
        service=PortfolioService(lambda:data)
        self.assertIn('가상회사: ▼14.34%',service.reply('실현','FAKE'))

    def snapshot(self):
        return dict(schema_version=1, generated_at='2026-10-29T11:00:00Z', holdings=[],
                    realized=[dict(name='가상회사',return_pct='-14.343', last_trade_date='2026-10-28',
                                   account='secret',realized_profit='123',currency='KRW')])

    def test_exact_realized_layout(self):
        service=PortfolioService(self.snapshot)
        self.assertEqual(service.reply('실현','가상회사'),
                         '[실현 수익률]\n· 가상회사: ▼14.34%\n\n최종 거래일 : 2026-10-28\n갱신 일자: 2026-10-29')

    def test_invalid_trade_date_is_unknown_not_a_fabricated_date(self):
        data=self.snapshot();data['realized'][0]['last_trade_date']='2026-00-00'
        text=PortfolioService(lambda:data).reply('실현','가상회사')
        self.assertIn('최종 거래일 : 미확인',text)
        self.assertNotIn('2026-00-00',text)

    def test_arrow_positive_flat_unknown_and_list_stays_navigation(self):
        for value,expected in [('1.234','▲1.23%'),('0','0.00%'),(None,'미확인')]:
            self.assertEqual(arrow_percent(value),expected)
        text=PortfolioService(self.snapshot).reply('실현')
        self.assertIn('· 가상회사(코드 미확인)',text)
        self.assertNotIn('상세:',text)
        self.assertNotIn('최종 거래일',text)

    def test_trade_dates_remain_associated_with_each_record(self):
        data=self.snapshot()
        data['realized'].append(dict(data['realized'][0],return_pct='1',last_trade_date='2026-10-27'))
        text=PortfolioService(lambda:data).reply('실현','가상회사')
        self.assertIn('▼14.34%\n\n최종 거래일 : 2026-10-28',text)
        self.assertIn('▲1.00%\n\n최종 거래일 : 2026-10-27',text)
        self.assertNotIn('secret',text)

    def test_only_confirmed_unlisted_name_is_overridden(self):
        rows=[dict(name='오아시스',currency='KRW',ticker=''),dict(name='다른회사',currency='KRW',ticker='')]
        text=PortfolioService().holdings_text(rows,'2026-10-29')
        self.assertIn('오아시스(비상장)',text)
        self.assertIn('다른회사(코드 미확인)',text)


if __name__=='__main__':
    unittest.main()
