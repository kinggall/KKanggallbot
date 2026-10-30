from datetime import datetime
from decimal import Decimal as D
import unittest
from unittest.mock import Mock, patch

from stockbot.investor_flows import (FLOW_MARKETS, FlowSnapshot, InvestorFlows,
                                    KISFlowLoader, parse_snapshot, amount_text)
from stockbot.market_data import MarketDataError
from stockbot.stock_quotes import KST
from stockbot import stock_commands


NOW=datetime(2026,10,30,10,25,tzinfo=KST)


class FlowTests(unittest.TestCase):
    def test_official_five_market_codes(self):
        self.assertEqual([(x.market,x.sector) for x in FLOW_MARKETS],
                         [('KSP','0001'),('KSQ','1001'),('K2I','F001'),('K2I','OC01'),('K2I','OP01')])

    def test_amounts_not_share_or_contract_counts_and_million_conversion(self):
        data={'output':[{'prsn_ntby_tr_pbmn':'123400','frgn_ntby_tr_pbmn':'-345600',
                         'orgn_ntby_tr_pbmn':'222200','prsn_ntby_qty':'999999999'}]}
        row=parse_snapshot(data,NOW)
        self.assertEqual(row.amounts,(D(123400),D(-345600),D(222200)))
        self.assertEqual(amount_text(row.amounts[0]),'+1,234')
        self.assertEqual(amount_text(D(-123)), '-1.23')
        self.assertEqual(amount_text(D(0)), '0')
        self.assertEqual(amount_text(None),'미확인')

    def test_missing_values_are_not_zero_and_net_can_be_buy_minus_sell(self):
        row=parse_snapshot({'output':{'prsn_shnu_tr_pbmn':'200','prsn_seln_tr_pbmn':'250',
                                     'frgn_ntby_tr_pbmn':'0'}},NOW)
        self.assertEqual(row.amounts,(D(-50),D(0),None))
        with self.assertRaises(MarketDataError):parse_snapshot({'output':[{'prsn_ntby_qty':'100'}]},NOW)

    def test_multiple_current_rows_are_not_summed_or_randomly_selected(self):
        row={'prsn_ntby_tr_pbmn':'100'}
        with self.assertRaises(MarketDataError):parse_snapshot({'output':[row,row]},NOW)

    def test_loader_uses_only_allowed_public_endpoint(self):
        adapter=Mock()
        with patch('stockbot.investor_flows.query',return_value={'output':{'prsn_ntby_tr_pbmn':'100'}}) as query:
            KISFlowLoader(adapter,now=lambda:NOW)(FLOW_MARKETS[3])
        self.assertEqual(query.call_args.args[2],{'FID_INPUT_ISCD':'K2I','FID_INPUT_ISCD_2':'OC01'})
        self.assertIn('/quotations/inquire-investor-time-by-market',query.call_args.args[1])

    def test_layout_three_space_indent_signed_amounts_and_partial_failure(self):
        def load(market):
            if market.key=='put':raise RuntimeError('secret-token')
            return FlowSnapshot((D(123400),D(-345600),D(222200)),NOW)
        text=InvestorFlows(load).reply()
        self.assertIn('[투자자 순매수 · 억원]',text)
        self.assertIn('🇰🇷 코스피\n   개인 +1,234 / 외국인 -3,456\n   기관 +2,222',text)
        self.assertIn('풋옵션: 조회 불가',text)
        self.assertIn('조회 기준: 2026-10-30. 10:25\n출처: 한국투자증권',text)
        self.assertNotIn('secret-token',text)

    def test_no_expired_success_is_relabelled_current_after_failure(self):
        clock=[0]
        loader=Mock(side_effect=[FlowSnapshot((D(0),D(0),D(0)),NOW),RuntimeError('offline')])
        service=InvestorFlows(loader,monotonic=lambda:clock[0])
        self.assertIsNotNone(service.load(FLOW_MARKETS[0]))
        clock[0]=14;self.assertIsNotNone(service.load(FLOW_MARKETS[0]))
        self.assertEqual(loader.call_count,1)
        clock[0]=16;self.assertIsNone(service.load(FLOW_MARKETS[0]))

    def test_command_routes_to_same_room_without_reading_private_portfolio(self):
        class Inline:
            def submit(self,fn):fn()
        with patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.FLOWS,'reply',return_value='fixture') as flow,patch.object(stock_commands.PORTFOLIO,'reply') as portfolio,patch.object(stock_commands.requests,'post') as post:
            self.assertEqual(stock_commands.handle('!수급','room','http://local')[1],200)
            flow.assert_called_once();portfolio.assert_not_called()
            self.assertEqual(post.call_args.kwargs['json']['room'],'room')

    def test_help_is_only_jugall(self):
        import bot
        self.assertIn('!수급',stock_commands.INVESTMENT_HELP)
        for value in bot.COMMANDS.values():self.assertNotIn('!수급',value)


if __name__=='__main__':unittest.main()
