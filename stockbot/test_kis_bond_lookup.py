from datetime import datetime
from decimal import Decimal as D
import io
import zipfile
import unittest
from unittest.mock import Mock
import requests

from stockbot.kis_yields import parse_master, parse_current_chart, complete_yields, BondMaster, maturity_key, public_rows, lookup_failure
from stockbot.market_data import MarketDataError
from stockbot.stock_quotes import KST


NOW=datetime(2026,10,30,10,tzinfo=KST)


def master_zip(rows):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        archive.writestr('frgn_code.mst','\n'.join(
            f'{kind}{code:<10}{english:<39}{korean:<25}XXXX0000000000'
            for kind,code,english,korean in rows).encode('cp949'))
    return buffer.getvalue()


def quote(code,name,value='4.12',previous='4.10'):
    return {'output1':{'stck_shrn_iscd':code,'hts_kor_isnm':name,
                       'ovrs_nmix_prpr':value,'ovrs_nmix_prdy_clpr':previous},
            'output2':[{'stck_bsop_date':'20261030','ovrs_nmix_prpr':value}]}


class BondLookupTests(unittest.TestCase):
    def test_diagnostics_keep_failure_stage_but_not_secrets(self):
        response=Mock(status_code=403)
        error=requests.HTTPError('secret-token-url',response=response)
        self.assertEqual(lookup_failure(error),'master HTTP 403')
        self.assertEqual(lookup_failure(ValueError('secret-token-url')),'ValueError')
        self.assertEqual(lookup_failure(MarketDataError('KIS bond instrument identity mismatch')),
                         'KIS bond instrument identity mismatch')

    def test_quote_parse_failure_is_preserved_in_candidate_diagnostics(self):
        master=Mock();master.load.return_value={'us2':[{'code':'B2','name':'미국 2년','english':''}]}
        result,details,errors=complete_yields({},NOW,master,lambda *args:quote('WRONG','미국 2년'))
        self.assertEqual(details[0]['failure'],'KIS bond instrument identity mismatch')
        self.assertEqual(errors['us2'],'KIS bond instrument identity mismatch')
    def test_nested_and_suffixed_output_groups_do_not_lose_maturities(self):
        data={'output3':{'rows':[{'hts_kor_isnm1':'국고채 2년','bond_mnrt_prpr1':'3.1',
                                 'stck_bsop_date1':'20261030'}]}}
        rows=public_rows(data)
        self.assertEqual(rows[0]['hts_kor_isnm'],'국고채 2년')
        self.assertEqual(rows[0]['bond_mnrt_prpr'],'3.1')

    def test_country_tenor_english_and_korean_variants(self):
        for name in ('United States 2-Year Bond Yield','US 2 YR Treasury','미국2년T-NOTE','US T-Note 2Y'):
            self.assertEqual(maturity_key(name),'us2')
        self.assertEqual(maturity_key('Korea Government Bond 5 Years'),'kr5')
        self.assertIsNone(maturity_key('US 12 Year Treasury'))
        self.assertIsNone(maturity_key('US 2 Year Bond ETF'))
        self.assertIsNone(maturity_key('Japan 2 Year Treasury'))

    def test_master_matches_country_maturity_and_market_not_guessed_codes(self):
        payload=master_zip([('I','B2','United States 2-Year Bond Yield','미국 국채 2년'),
                            ('I','K5','Korea Government Bond 5 Years','국고채 5년'),
                            ('N','ETF','United States 2-Year Bond ETF','미국 2년 ETF'),
                            ('I','J2','Japan 2-Year Bond Yield','일본 국채 2년')])
        rows=parse_master(payload)
        self.assertEqual(set(rows),{'us2','kr5'})
        self.assertEqual(rows['us2'][0]['code'],'B2')

    def test_current_header_is_required_and_daily_candle_cannot_replace_it(self):
        record={'code':'B2','name':'미국 2년','english':'US 2 Year Treasury'}
        data=quote('B2','미국 2년')
        obs=parse_current_chart(data,'us2',record,NOW)
        self.assertEqual(obs.value,D('4.12'))
        data['output1']['ovrs_nmix_prpr']=''
        with self.assertRaises(MarketDataError):parse_current_chart(data,'us2',record,NOW)

    def test_wrong_symbol_maturity_and_mismatched_latest_candle_rejected(self):
        record={'code':'B2','name':'미국 2년','english':'US 2 Year Treasury'}
        for code,name in [('B5','미국 2년'),('B2','미국 5년'),('B2','일본 2년')]:
            with self.assertRaises(MarketDataError):parse_current_chart(quote(code,name),'us2',record,NOW)
        data=quote('B2','미국 2년')
        data['output2'].append({'stck_bsop_date':'20261031','ovrs_nmix_prpr':'4.99'})
        self.assertEqual(parse_current_chart(data,'us2',record,NOW).value,D('4.12'))
        data['output2'].append({'stck_bsop_date':'20261030','ovrs_nmix_prpr':'4.99'})
        with self.assertRaises(MarketDataError):parse_current_chart(data,'us2',record,NOW)

    def test_all_eight_maturities_resolve_only_from_kis_master(self):
        records={p+str(y):[{'code':p+str(y),'name':('미국 ' if p=='us' else '국고채 ')+str(y)+'년',
                           'english':''}] for p in ('us','kr') for y in (2,5,10,30)}
        master=Mock();master.load.return_value=records
        def query(path,params):
            self.assertEqual(params['FID_COND_MRKT_DIV_CODE'],'I')
            code=params['FID_INPUT_ISCD']
            return quote(code,records[code][0]['name'])
        result,details,errors=complete_yields({},NOW,master,query)
        self.assertEqual(set(result),set(records))
        self.assertEqual(len(details),8);self.assertEqual(errors,{})

    def test_master_missing_does_not_erase_valid_comp_interest_quote(self):
        data={'output1':[{'hts_kor_isnm':'미국 10년T-NOTE','bond_mnrt_prpr':'4.98',
               'stck_bsop_date':'20261029','bond_mnrt_prdy_vrss':'-0.07','prdy_vrss_sign':'5'}]}
        master=Mock();master.load.side_effect=MarketDataError('unavailable')
        query=Mock()
        result,details,errors=complete_yields(data,NOW,master,query)
        self.assertEqual(result['us10'].value,D('4.98'))
        query.assert_not_called();self.assertIn('master',errors)

    def test_public_diagnostics_compare_current_header_to_table(self):
        data={'output1':[{'hts_kor_isnm':'미국 10년T-NOTE','bond_mnrt_prpr':'4.98',
               'stck_bsop_date':'20261030','bond_mnrt_prdy_vrss':'-0.07','prdy_vrss_sign':'5'}]}
        master=Mock();master.load.return_value={'us10':[{'code':'B10','name':'미국 10년','english':''}]}
        result,details,errors=complete_yields(data,NOW,master,lambda *args:quote('B10','미국 10년','5.00'))
        self.assertEqual(result['us10'].value,D('5.00'))
        self.assertEqual(details[0]['difference_from_table'],'0.02')

    def test_older_header_date_does_not_replace_newer_table_value(self):
        data={'output1':[{'hts_kor_isnm':'미국 10년T-NOTE','bond_mnrt_prpr':'4.98',
               'stck_bsop_date':'20261030','bond_mnrt_prdy_vrss':'-0.07','prdy_vrss_sign':'5'}]}
        master=Mock();master.load.return_value={'us10':[{'code':'B10','name':'미국 10년','english':''}]}
        old=quote('B10','미국 10년','5.00')
        old['output2'][0]['stck_bsop_date']='20261029'
        result,details,errors=complete_yields(data,NOW,master,lambda *args:old)
        self.assertEqual(result['us10'].value,D('4.98'))
        self.assertEqual(details[0]['kept'],'newer_comp_interest_date')

    def test_master_cache_and_failure_backoff(self):
        clock=[0]
        response=Mock();response.content=master_zip([('I','B2','US 2 Year Treasury','미국 2년')])
        get=Mock(return_value=response)
        master=BondMaster(get=get,monotonic=lambda:clock[0])
        self.assertEqual(master.load(),master.load());self.assertEqual(get.call_count,1)
        clock[0]=86401;response.content=b'invalid zip'
        for unused in range(2):
            with self.assertRaises(MarketDataError):master.load()
        self.assertEqual(get.call_count,2)


if __name__=='__main__':unittest.main()
