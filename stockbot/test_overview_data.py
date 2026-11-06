import json
import unittest
from .overview_data import total_profit


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
