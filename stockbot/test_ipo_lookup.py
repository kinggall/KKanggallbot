from datetime import datetime
import io
import zipfile
import unittest
from unittest.mock import Mock

from stockbot.listing_lookup import DailyListingLookup,parse_listing
from stockbot.portfolio import PortfolioService
from stockbot.stock_quotes import StockService,KST


def master_payload(filename,tail,rows):
    stream=io.BytesIO()
    text=''.join(f'{code:<9}{"KR"+code+"0000":12}{name:<40}'+('0'*(tail-1))+'\n' for name,code in rows)
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr(filename,text.encode('cp949'))
    return stream.getvalue()


class IPOLookupTests(unittest.TestCase):
    def test_official_master_short_code_name_and_newline_offsets(self):
        for filename,tail in [('kospi_code.mst',228),('kosdaq_code.mst',222)]:
            rows=parse_listing(master_payload(filename,tail,[('가상공모주','000001'),('가상ETF','0123A0')]),filename,tail)
            self.assertEqual(rows['가상공모주'],{'000001'})
            self.assertEqual(rows['가상etf'],{'0123A0'})

    def test_unknown_ticker_names_do_not_collapse_and_oasis_bypasses_lookup(self):
        rows=[dict(name=name,ticker='미확인',currency='KRW') for name in ('인텔리빅스','크리에이츠','오아시스')]
        lookup=Mock(return_value='')
        text=PortfolioService(ticker_lookup=lookup).holdings_text(rows,'2026-10-30')
        self.assertIn('인텔리빅스(코드 미확인)',text)
        self.assertIn('크리에이츠(코드 미확인)',text)
        self.assertIn('오아시스(비상장)',text)
        self.assertEqual(lookup.call_count,2)
        self.assertTrue(all(call.args[0]!='오아시스' for call in lookup.call_args_list))
        self.assertTrue(all(row['ticker']=='미확인' for row in rows))

    def test_resolved_code_is_used_in_list_and_quote_without_changing_snapshot(self):
        data={'schema_version':1,'generated_at':'2026-10-30','realized':[],
              'holdings':[{'name':'가상공모주','ticker':'미확인','currency':'KRW','average':'100'}]}
        quote=Mock(return_value={'price':'110','change':'10','percent':'10','fetched_at':'2026-10-30'})
        service=PortfolioService(loader=lambda:data,ticker_lookup=lambda *args:'000001',quote_loader=quote)
        self.assertIn('가상공모주(000001)',service.reply('보유'))
        self.assertIn('현재가: 110원',service.reply('보유','가상공모주'))
        quote.assert_called_once_with('000001','KRW')
        self.assertEqual(data['holdings'][0]['ticker'],'미확인')

    def test_listing_api_validates_exact_company_and_code_and_refreshes_on_kst_day(self):
        today=[datetime(2026,10,30,23,59,tzinfo=KST)]
        def get(url,**kwargs):
            filename='kosdaq_code.mst' if 'kosdaq' in url else 'kospi_code.mst'
            tail=222 if 'kosdaq' in filename else 228
            response=Mock();response.content=master_payload(filename,tail,[('가상공모주','000001')])
            return response
        get=Mock(side_effect=get)
        basic=Mock(return_value={'itemCode':'000001','stockName':'가상공모주','nationType':'KOR'})
        lookup=DailyListingLookup(basic,get=get,now=lambda:today[0])
        self.assertEqual(lookup('가상공모주'),'000001')
        self.assertEqual(lookup('가상공모주'),'000001')
        self.assertEqual(get.call_count,2);self.assertEqual(basic.call_count,1)
        today[0]=datetime(2026,10,31,0,0,tzinfo=KST)
        self.assertEqual(lookup('가상공모주'),'000001')
        self.assertEqual(get.call_count,4);self.assertEqual(basic.call_count,2)

    def test_same_day_new_listing_retries_after_five_minutes_without_guessing(self):
        clock=[0];listed=[False]
        def get(url,**kwargs):
            filename='kosdaq_code.mst' if 'kosdaq' in url else 'kospi_code.mst'
            tail=222 if 'kosdaq' in filename else 228
            names=[('기존회사','000002')]+([('가상공모주','000001')] if listed[0] else [])
            response=Mock();response.content=master_payload(filename,tail,names)
            return response
        basic=Mock(return_value={'itemCode':'000001','stockName':'가상공모주','nationType':'KOR'})
        lookup=DailyListingLookup(basic,get=get,now=lambda:datetime(2026,10,30,tzinfo=KST),monotonic=lambda:clock[0])
        self.assertEqual(lookup('가상공모주'),'');basic.assert_not_called()
        listed[0]=True;clock[0]=301
        self.assertEqual(lookup('가상공모주'),'000001')

    def test_basic_api_name_mismatch_does_not_assign_ticker(self):
        lookup=DailyListingLookup(Mock(return_value={'itemCode':'000001','stockName':'다른회사','nationType':'KOR'}))
        lookup._catalog=Mock(return_value={'가상공모주':{'000001'}})
        self.assertEqual(lookup('가상공모주'),'')

    def test_stock_service_uses_fresh_listing_lookup_and_unresolved_api_failure_keeps_rows(self):
        lookup=Mock(return_value='000001')
        service=StockService(codes_loader=lambda:{},listing_lookup=lookup)
        self.assertEqual(service.ticker_for_name('가상공모주','KRW'),'000001')
        lookup.assert_called_once_with('가상공모주')
        portfolio=PortfolioService(ticker_lookup=Mock(side_effect=ValueError('secret-token')))
        text=portfolio.holdings_text([dict(name='가상공모주',ticker='미확인',currency='KRW')],'2026-10-30')
        self.assertIn('가상공모주(코드 미확인)',text);self.assertNotIn('secret-token',text)


if __name__=='__main__':unittest.main()
