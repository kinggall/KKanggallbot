import json
import unittest
from unittest.mock import Mock
from .overview_data import total_profit, current_profit, embedded_json


class OverviewDataTests(unittest.TestCase):
    def html(self, stale=False, ipo=None, missing=False):
        data = dict(accounts=[dict(id='a')], holdings=[dict(account_id='a', name='test', currency='KRW',
                    quantity=2, purchase=100, ipo_offer_price=ipo)], cash=[dict(account_id='a',currency='KRW',amount=10)],
                    symbol_map={'test':'KRX:000001'}, net_return={'a':dict(has_records=True,available=not missing,
                    issues=[],opening=200,deposits=20,stock_in=0,withdrawals=10,stock_out=0)})
        market = {'quotes':[dict(ticker='KRX:000001',currency='KRW',price=80,stale=stale)]}
        return 'const DATA='+json.dumps(data)+';window.DOMINO_SNAPSHOT_QUOTES='+json.dumps(market)+';'

    def test_stock_cash_and_net_principal(self):
        self.assertEqual(total_profit(self.html()), -40)

    def test_stale_stock_excluded_with_its_cost(self):
        self.assertEqual(total_profit(self.html(stale=True)), -100)

    def test_ipo_valuation(self):
        self.assertEqual(total_profit(self.html(stale=True,ipo=90)), -20)

    def test_incomplete_fails_closed(self):
        with self.assertRaises(ValueError):
            total_profit(self.html(missing=True))

    def test_no_javascript_execution(self):
        with self.assertRaises(ValueError):
            total_profit('const DATA=process.exit();')

    def test_refresh_price_keeps_baseline_cash_and_principal(self):
        loader = Mock(return_value={'price':90})
        fx = Mock(side_effect=AssertionError('KRW only'))
        self.assertEqual(current_profit(self.html(),loader,fx),-20)
        loader.assert_called_once_with('KRX:000001','KRW')
        fx.assert_not_called()

    def test_live_failure_never_uses_snapshot_price(self):
        for row in ({'price':None},{'price':0},{'price':'NaN'},{'price':90,'stale':True},{'price':90,'error':'offline'}):
            with self.subTest(row=row),self.assertRaises(ValueError):
                current_profit(self.html(),lambda *args:row,lambda:1300)
        with self.assertRaises(OSError):
            current_profit(self.html(),Mock(side_effect=OSError()),lambda:1300)

    def test_previously_excluded_stock_reinstates_its_cost(self):
        self.assertEqual(current_profit(self.html(stale=True),lambda *args:{'price':90},lambda:1300),-20)

    def test_current_fx_revalues_stock_not_snapshot_cash(self):
        data=embedded_json(self.html(),r'const DATA=')
        data['holdings'][0].update(currency='USD',cost_krw=20000)
        data['cash'][0].update(currency='USD',amount=100)
        data['symbol_map']={'test':'NASDAQ:FAKE'}
        data['net_return']['a'].update(opening=150000,deposits=0,withdrawals=0)
        market={'quotes':[dict(ticker='NASDAQ:FAKE',currency='USD',price=10),dict(ticker='CURRENCY:USDKRW',price=1000)]}
        html='const DATA='+json.dumps(data)+';window.DOMINO_SNAPSHOT_QUOTES='+json.dumps(market)+';'
        self.assertEqual(total_profit(html),-30000)
        self.assertEqual(current_profit(html,lambda *args:{'price':12},lambda:1100),-23600)
        with self.assertRaises(ValueError):
            current_profit(html,lambda *args:{'price':12},lambda:None)

    def test_repeated_ticker_fetches_once(self):
        data=embedded_json(self.html(),r'const DATA=')
        data['holdings'].append(dict(data['holdings'][0]))
        market={'quotes':[dict(ticker='KRX:000001',currency='KRW',price=80)]}
        html='const DATA='+json.dumps(data)+';window.DOMINO_SNAPSHOT_QUOTES='+json.dumps(market)+';'
        loader=Mock(return_value={'price':90})
        self.assertEqual(current_profit(html,loader,lambda:1300),160)
        self.assertEqual(loader.call_count,1)
