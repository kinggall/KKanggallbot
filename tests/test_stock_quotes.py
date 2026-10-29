from datetime import datetime, timezone
from decimal import Decimal as D
import unittest
from unittest.mock import Mock

from stockbot import stock_quotes as stocks


def output(code='000001', price='900', change='100', sign='5', volume='1234567', turnover='6400000000'):
    return dict(stck_shrn_iscd=code, stck_prpr=price, prdy_vrss=change,
                prdy_vrss_sign=sign, acml_vol=volume, acml_tr_pbmn=turnover)


def service(**kwargs):
    defaults=dict(codes_loader=lambda:{'가상회사':'KRX:000001'},
                  quote_loader=lambda code:output(code),
                  basic_loader=lambda code:dict(stockName='가상회사',marketStatus='OPEN'))
    defaults.update(kwargs)
    return stocks.StockService(**defaults)


class StockQuoteTests(unittest.TestCase):
    def test_actual_turnover_is_not_price_times_volume(self):
        reply=service().reply('가상회사')
        self.assertIn('🔵 가상회사 주가 🔵',reply)
        self.assertIn('현재가: 900원 (▼10.00%)',reply)
        self.assertIn('전일대비: -100원',reply)
        self.assertIn('거래량: 1,234,567주',reply)
        self.assertIn('거래대금: 64억원',reply)
        self.assertIn('한국투자증권',reply)

    def test_positive_flat_and_zero_volume(self):
        rising=service(quote_loader=lambda c:output(c,'1100','100','2')).reply('가상회사')
        self.assertIn('🔴',rising);self.assertIn('▲10.00%',rising);self.assertIn('+100원',rising)
        flat=service(quote_loader=lambda c:output(c,'1000','0','3','0','0')).reply('가상회사')
        self.assertIn('⚪',flat);self.assertIn('0.00%',flat);self.assertIn('거래량: 0주',flat);self.assertIn('거래대금: 0원',flat)

    def test_numeric_code_skips_name_master_and_uses_verified_name(self):
        master=Mock(side_effect=AssertionError('should not load catalog'))
        reply=service(codes_loader=master).reply('000001')
        self.assertIn('가상회사 주가',reply);master.assert_not_called()

    def test_ambiguous_name_is_not_arbitrarily_selected(self):
        quote=Mock()
        s=service(codes_loader=lambda:{'TEST':'KRX:000001','test':'KOSDAQ:000002'},quote_loader=quote)
        reply=s.reply('test')
        self.assertIn('000001',reply);self.assertIn('000002',reply);quote.assert_not_called()

    def test_unknown_name_and_empty_usage_do_not_call_quote_api(self):
        quote=Mock();master=Mock(return_value={'가상회사':'KRX:000001'});s=service(quote_loader=quote,codes_loader=master)
        self.assertEqual(s.reply(''),stocks.USAGE);master.assert_not_called()
        self.assertIn('찾지 못했습니다',s.reply('존재하지않는종목'));quote.assert_not_called()

    def test_cache_reuses_price_for_five_seconds_with_original_quote_time(self):
        tick=[0.0];quote=Mock(side_effect=lambda c:output(c));s=service(quote_loader=quote,monotonic=lambda:tick[0])
        first=s.reply('가상회사');tick[0]=4
        self.assertEqual(s.reply('가상회사'),first);self.assertEqual(quote.call_count,1)
        tick[0]=6;s.reply('가상회사');self.assertEqual(quote.call_count,2)

    def test_wrong_symbol_and_bad_price_never_become_a_quote(self):
        for payload in (output('000002'),output(price='NaN'),output(price='0')):
            with self.assertRaises(stocks.QuoteError):
                stocks.parse_quote(payload,'000001','가상회사',datetime.now(timezone.utc))

    def test_missing_optional_data_is_not_fabricated_as_zero(self):
        payload=dict(stck_shrn_iscd='000001',stck_prpr='1000')
        reply=service(quote_loader=lambda c:payload).reply('가상회사')
        self.assertIn('등락률 미확인',reply);self.assertIn('전일대비: —',reply)
        self.assertIn('거래량: —',reply);self.assertIn('거래대금: —',reply)

    def test_provider_errors_do_not_leak_exception_text(self):
        loader=Mock(side_effect=ValueError('private-fake-secret-token'))
        with self.assertLogs('stockbot.stock_quotes',level='WARNING') as logs:
            reply=service(quote_loader=loader).reply('가상회사')
        self.assertNotIn('private-fake-secret-token',reply+' '.join(logs.output))
        self.assertIn('불러오지 못했습니다',reply)

    def test_metadata_failure_keeps_valid_kis_price(self):
        reply=service(basic_loader=Mock(side_effect=OSError('offline'))).reply('가상회사')
        self.assertIn('900원',reply)

    def test_market_closed_is_labelled_as_recent_quote(self):
        reply=service(basic_loader=lambda c:dict(stockName='가상회사',marketStatus='CLOSE')).reply('가상회사')
        self.assertIn('장외 · 최근 시세',reply)
