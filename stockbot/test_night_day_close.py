from datetime import datetime, date
from decimal import Decimal as D
import unittest
from unittest.mock import Mock, patch

from stockbot.night_futures import KISNightFutures, regular_session_close, CHART
from stockbot.market_data import GROUPS, format_line, MarketDataError
from stockbot.stock_quotes import KST


def bars(code,day,hour,price,reference='915.10'):
    return {'output1':{'futs_shrn_iscd':code,'futs_prpr':price,'futs_prdy_clpr':reference},
            'output2':[{'stck_bsop_date':day,'stck_cntg_hour':hour,'futs_prpr':price}]}


class DayReferenceTests(unittest.TestCase):
    def test_reported_price_uses_day_close_not_prior_night_close_or_open(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,19,tzinfo=KST))
        board={'output':[{'futs_shrn_iscd':'A01612','hts_kor_isnm':'F 202612','hts_rmnn_dynu':'40'}]}
        night=bars('A01612','20261030','190000','887.90')
        night['output1']['futs_oprc']='905.22'
        day=bars('A01612','20261030','154500','899.45')
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,night,day]) as query:
            result=adapter()
        self.assertEqual(result.previous,D('899.45'))
        self.assertEqual(result.value,D('887.90'))
        self.assertIn('(▼11.55, ▼1.28%)',format_line(GROUPS['야선'][0],result))
        params=query.call_args.args[2]
        self.assertEqual(params['FID_COND_MRKT_DIV_CODE'],'F')
        self.assertEqual(params['FID_INPUT_DATE_1'],'20261030')
        self.assertEqual(params['FID_INPUT_HOUR_1'],'154500')

    def test_after_midnight_and_next_morning_use_preceding_days_close(self):
        for hour,bar_hour in [(1,'250000'),(8,'300000')]:
            with self.subTest(hour=hour):
                adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,31,hour,tzinfo=KST))
                board={'output':[{'futs_shrn_iscd':'A01612','hts_kor_isnm':'F 202612','hts_rmnn_dynu':'40'}]}
                night=bars('A01612','20261030',bar_hour,'887.90')
                day=bars('A01612','20261030','154500','899.45')
                with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,night,day]) as query:
                    self.assertEqual(adapter().previous,D('899.45'))
                self.assertEqual(query.call_args.args[2]['FID_INPUT_DATE_1'],'20261030')

    def test_missing_day_close_preserves_night_price_without_fake_percentage(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,19,tzinfo=KST))
        board={'output':[{'futs_shrn_iscd':'A01612','hts_kor_isnm':'F 202612','hts_rmnn_dynu':'40'}]}
        night=bars('A01612','20261030','190000','887.90')
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,night,ValueError('offline')]):
            result=adapter()
        self.assertEqual(result.value,D('887.90'));self.assertIsNone(result.previous)
        self.assertIn('증감 미확인',format_line(GROUPS['야선'][0],result))

    def test_wrong_contract_date_intraday_bar_and_conflicting_close_are_rejected(self):
        for data in (bars('OTHER','20261030','154500','899.45'),
                     bars('A01612','20261029','154500','899.45'),
                     bars('A01612','20261030','153000','899.45')):
            with self.assertRaises(MarketDataError):regular_session_close(data,'A01612',date(2026,10,30))
        data=bars('A01612','20261030','154500','899.45')
        data['output2'].append({'stck_bsop_date':'20261030','stck_cntg_hour':'154500','futs_prpr':'900'})
        with self.assertRaises(MarketDataError):regular_session_close(data,'A01612',date(2026,10,30))

    def test_reference_cache_is_separate_for_contract_and_date(self):
        adapter=KISNightFutures(Mock())
        response=bars('A01612','20261030','154500','899.45')
        with patch('stockbot.night_futures.query',return_value=response) as query:
            self.assertEqual(adapter.day_close(Mock(),'A01612',date(2026,10,30)),D('899.45'))
            self.assertEqual(adapter.day_close(Mock(),'A01612',date(2026,10,30)),D('899.45'))
            self.assertEqual(query.call_count,1)
            self.assertIsNone(adapter.day_close(Mock(),'A01703',date(2026,10,30)))
            self.assertEqual(query.call_count,2)


if __name__=='__main__':unittest.main()
