from datetime import datetime
from decimal import Decimal as D
import unittest
from unittest.mock import Mock,patch

from stockbot.tradingview_forex import TradingViewForex,SYMBOLS
from stockbot.market_data import MarketProvider,MarketService,GROUPS,MarketDataError
from stockbot.stock_quotes import KST


NOW=datetime(2026,10,30,21,tzinfo=KST)


def response_data():
    return {'data':[{'s':'FX_IDC:USDKRW','d':['1337.89','-5.10','streaming']},
                    {'s':'TVC:DXY','d':['101.65','-0.39','streaming']}]}


class ForexTests(unittest.TestCase):
    def test_exact_spot_pair_and_cash_dollar_index(self):
        self.assertEqual({item.key:item.symbol for item in GROUPS['환율']},SYMBOLS)
        self.assertTrue(all(item.provider=='tradingview_forex' for item in GROUPS['환율']))

    def test_both_values_use_single_global_request_with_correct_price_range(self):
        response=Mock();response.json.return_value=response_data()
        post=Mock(return_value=response)
        result=TradingViewForex(post=post,now=lambda:NOW)()
        self.assertEqual(result['usdkrw'].value,D('1337.89'))
        self.assertEqual(result['usdkrw'].previous,D('1342.99'))
        self.assertEqual(result['dxy'].value,D('101.65'))
        self.assertEqual(post.call_count,1)
        self.assertEqual(post.call_args.args[0],'https://scanner.tradingview.com/global/scan')
        self.assertEqual(post.call_args.kwargs['json']['markets'],[])
        self.assertEqual(post.call_args.kwargs['json']['symbols']['tickers'],list(SYMBOLS.values()))

    def test_no_yahoo_fallback_and_current_layout(self):
        response=Mock();response.json.return_value=response_data()
        provider=MarketProvider()
        provider.tv_forex=TradingViewForex(post=Mock(return_value=response),now=lambda:NOW)
        with patch.object(provider,'yahoo') as yahoo:
            text=MarketService(provider).reply('환율')
        yahoo.assert_not_called()
        self.assertIn('💵 USD/KRW: 1,337.89\n   (▼5.10, ▼0.38%)',text)
        self.assertIn('💵 달러인덱스: 101.65\n   (▼0.39, ▼0.38%)',text)
        self.assertIn('조회 기준: 2026-10-30. 21:00\n출처: TradingView',text)

    def test_failure_stays_failed_without_mixing_yahoo_or_old_success(self):
        provider=MarketProvider()
        provider.tv_forex=Mock(side_effect=MarketDataError('secret-token'))
        provider.tv_forex.public_diagnostics=[{'scanner':'global','failure':'HTTP 403'}]
        with patch.object(provider,'yahoo') as yahoo:
            text=MarketService(provider).reply('환율')
        yahoo.assert_not_called()
        self.assertEqual(text.count('조회 불가'),2)
        self.assertIn('연결 상태: TradingView 접근 거절(HTTP 403)',text)
        self.assertNotIn('secret-token',text)

    def test_forex_route_scope_and_partial_data(self):
        first=Mock();first.json.return_value={'data':[]}
        second=Mock();second.json.return_value={'data':[response_data()['data'][0]]}
        third=Mock();third.json.return_value={'data':[]}
        post=Mock(side_effect=[first,second,third])
        result=TradingViewForex(post=post,now=lambda:NOW)()
        self.assertEqual(set(result),{'usdkrw'})
        self.assertEqual(post.call_args_list[1].args[0],'https://scanner.tradingview.com/forex/scan')
        self.assertEqual(post.call_args_list[1].kwargs['json']['markets'],['forex'])
        self.assertEqual(post.call_args_list[2].kwargs['json']['symbols']['tickers'],['TVC:DXY'])


if __name__=='__main__':unittest.main()
