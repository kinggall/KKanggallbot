from datetime import datetime
from decimal import Decimal as D
import unittest
from unittest.mock import Mock,patch

import requests

from stockbot.tradingview_yields import SYMBOLS,COLUMNS,TradingViewYields,parse_scanner,failure_summary
from stockbot.market_data import MarketProvider,MarketService,GROUPS,format_line,MarketDataError
from stockbot.stock_quotes import KST


NOW=datetime(2026,10,30,20,tzinfo=KST)


def scanner(symbols=None,mode='streaming'):
    return {'data':[{'s':symbol,'d':['4.594','-0.008',mode]} for symbol in (symbols or SYMBOLS.values())]}


class TradingViewTests(unittest.TestCase):
    def test_exact_eight_user_selected_yield_indices(self):
        self.assertEqual(list(SYMBOLS.values()),['TVC:KR02Y','TVC:KR05Y','TVC:KR10Y','TVC:KR30Y',
                                               'TVC:US02Y','TVC:US05Y','TVC:US10Y','TVC:US30Y'])
        self.assertEqual({item.key:item.symbol for item in GROUPS['금리']},SYMBOLS)

    def test_yield_not_coupon_or_price_and_percentage_point_change(self):
        result,errors,modes=parse_scanner(scanner(),NOW)
        self.assertEqual(len(result),8);self.assertEqual(errors,{})
        self.assertEqual(result['us2'].value,D('4.594'))
        self.assertEqual(result['us2'].previous,D('4.602'))
        self.assertIn('4.594%\n   (▼0.008, ▼0.17%)',format_line(GROUPS['금리'][4],result['us2']))

    def test_unknown_symbols_and_missing_values_are_not_invented(self):
        data={'data':[{'s':'NASDAQ:US02Y','d':[100,1,'streaming']},
                      {'s':'TVC:US02Y','d':[None,None,'streaming']}]}
        result,errors,modes=parse_scanner(data,NOW)
        self.assertEqual(result,{})
        self.assertEqual(errors['us2'],'missing or invalid yield')

    def test_delayed_unknown_and_eod_modes_are_not_called_realtime(self):
        for mode,label in [('delayed_streaming_900','15분 지연'),('delayed_streaming','지연 시세'),(None,'지연 여부 미확인')]:
            result,errors,modes=parse_scanner(scanner(mode=mode),NOW)
            self.assertIn(label,result['us2'].source)
        result,errors,modes=parse_scanner(scanner(mode='endofday'),NOW)
        self.assertFalse(result);self.assertEqual(errors['us2'],'daily-only feed rejected')

    def test_missing_delta_stays_unknown_and_duplicate_symbols_rejected(self):
        data={'data':[{'s':'TVC:US02Y','d':['4.594',None,'streaming']}]}
        result,errors,modes=parse_scanner(data,NOW)
        self.assertIsNone(result['us2'].previous)
        data['data'].append(data['data'][0])
        with self.assertRaises(MarketDataError):parse_scanner(data,NOW)

    def test_one_batch_request_no_login_cookies_or_other_providers(self):
        response=Mock();response.json.return_value=scanner()
        post=Mock(return_value=response)
        result=TradingViewYields(post=post,now=lambda:NOW)()
        self.assertEqual(len(result),8);self.assertEqual(post.call_count,1)
        kwargs=post.call_args.kwargs
        self.assertNotIn('cookies',kwargs);self.assertNotIn('auth',kwargs)
        self.assertEqual(kwargs['json']['columns'],list(COLUMNS))
        self.assertEqual(kwargs['json']['symbols']['tickers'],list(SYMBOLS.values()))
        self.assertEqual(post.call_args.args[0],'https://scanner.tradingview.com/global/scan')
        self.assertEqual(kwargs['json']['markets'],[])

    def test_empty_asset_scanner_tries_other_asset_route_not_other_data_source(self):
        first=Mock();first.json.return_value={'data':[]}
        second=Mock();second.json.return_value=scanner()
        post=Mock(side_effect=[first,second])
        result=TradingViewYields(post=post,now=lambda:NOW)()
        self.assertEqual(len(result),8)
        self.assertEqual(post.call_args.args[0],'https://scanner.tradingview.com/bond/scan')
        self.assertEqual(post.call_args.kwargs['json']['markets'],['bond'])

    def test_access_refusal_and_rate_limit_stop_routes_and_back_off(self):
        for status in (401,403,429):
            with self.subTest(status=status):
                response=Mock(status_code=status,headers={'Retry-After':'120'})
                response.raise_for_status.side_effect=requests.HTTPError('secret-token',response=response)
                post=Mock(return_value=response)
                loader=TradingViewYields(post=post,now=lambda:NOW,monotonic=lambda:0)
                with self.assertRaisesRegex(MarketDataError,'HTTP '+str(status)):loader()
                with self.assertRaisesRegex(MarketDataError,'retry backoff'):loader()
                self.assertEqual(post.call_count,1)
                self.assertNotIn('secret-token',str(loader.public_diagnostics))

    def test_service_preserves_heading_partial_results_and_tv_only_source(self):
        loader=Mock()
        loader.return_value=parse_scanner(scanner(['TVC:US02Y']),NOW)[0]
        provider=MarketProvider();provider.tv_yields=loader
        text=MarketService(provider).reply('금리')
        self.assertTrue(text.startswith('[국채 금리]\n\n'))
        self.assertIn('미국채 2년: 4.594%',text)
        self.assertIn('국고채 2년: 조회 불가',text)
        self.assertIn('출처: TradingView',text)
        self.assertNotIn('한국투자증권',text)
        self.assertEqual(loader.call_count,1)

    def test_all_failed_reply_exposes_safe_status_without_needing_pc_console(self):
        loader=Mock(side_effect=MarketDataError('secret-token'))
        loader.public_diagnostics=[{'scanner':'bond','failure':'HTTP 403'}]
        provider=MarketProvider();provider.tv_yields=loader
        text=MarketService(provider).reply('금리')
        self.assertIn('연결 상태: TradingView 접근 거절(HTTP 403)',text)
        self.assertEqual(text.count('조회 불가'),8)
        self.assertNotIn('secret-token',text)
        self.assertIsNone(failure_summary([{'failure':'secret-token'}]))

    def test_diagnostics_distinguish_no_symbols_from_daily_only_values(self):
        response=Mock();response.json.return_value={'data':[]}
        loader=TradingViewYields(post=Mock(return_value=response),now=lambda:NOW)
        with self.assertRaises(MarketDataError):loader()
        self.assertIn('global 0건',failure_summary(loader.public_diagnostics))
        response.json.return_value=scanner(mode='endofday')
        with self.assertRaises(MarketDataError):loader()
        self.assertIn('일별 전용 피드',failure_summary(loader.public_diagnostics))


if __name__=='__main__':unittest.main()
