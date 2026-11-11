import unittest
from unittest.mock import Mock
from .stock_quotes import StockService


def us_quote(symbol):
    return {'exchange':'NAS','rsym':'DNAS'+symbol,'curr':'USD','last':'10','base':'9'}


class MarketCollisionTests(unittest.TestCase):
    def service(self, listing):
        us=Mock(side_effect=us_quote)
        kr=Mock(side_effect=lambda code:{'stck_shrn_iscd':code,'stck_prpr':'100'})
        service=StockService(codes_loader=lambda:listing,us_loader=us,quote_loader=kr,basic_loader=lambda code:{})
        return service,us,kr

    def test_nc_name_and_alias_show_both_markets_without_quoting(self):
        for name in ('NC','엔씨소프트','NC소프트','엔씨'):
            service,us,kr=self.service({name:'KRX:036570'})
            for query in ('NC','nc','Nc'):
                text=service.reply(query)
                self.assertIn('036570 · 국내',text)
                self.assertIn('NC · 미국',text)
                self.assertIn('NACCO',text)
                self.assertIn('!주가 미국 NC',text)
                self.assertIn('!주가 국내 NC',text)
            us.assert_not_called();kr.assert_not_called()

    def test_one_through_four_english_letters_are_checked(self):
        for name in ('F','GS','DB','IBM','META'):
            service,us,kr=self.service({name:'KRX:000001'})
            text=service.reply(name)
            self.assertIn('000001 · 국내',text)
            self.assertIn(name+' · 미국',text)
            us.assert_not_called();kr.assert_not_called()

    def test_kb_alias_collision(self):
        service,us,kr=self.service({'KB금융':'KRX:105560'})
        text=service.reply('KB')
        self.assertIn('KB금융',text);self.assertIn('KB · 미국',text)
        us.assert_not_called();kr.assert_not_called()

    def test_explicit_us_and_domestic_code_resolve_the_choice(self):
        service,us,kr=self.service({'엔씨소프트':'KRX:036570'})
        self.assertIn('✔️ 현재가:',service.reply('미국 NC'))
        us.assert_called_once_with('NC');kr.assert_not_called()
        self.assertIn('✔️ 현재가:',service.reply('036570'))
        kr.assert_called_once_with('036570')

    def test_explicit_domestic_name_or_alias_does_not_call_us(self):
        for keyword in ('국내 nc','국내 NC','국내 엔씨소프트','국내 036570'):
            service,us,kr=self.service({'엔씨소프트':'KRX:036570'})
            self.assertIn('✔️ 현재가:',service.reply(keyword))
            kr.assert_called_once_with('036570');us.assert_not_called()
        service,us,kr=self.service({})
        self.assertIn('국내 종목을 찾지 못했습니다',service.reply('국내 AAPL'))
        us.assert_not_called();kr.assert_not_called()

    def test_no_domestic_collision_keeps_us_and_etf_partial_is_not_collision(self):
        service,us,kr=self.service({'SOL 글로벌DRAM반도체플러스':'KRX:0246X0'})
        self.assertIn('✔️ 현재가:',service.reply('DRAM'))
        us.assert_called_once_with('DRAM');kr.assert_not_called()

    def test_domestic_only_short_english_name(self):
        service,us,kr=self.service({'HLB':'KOSDAQ:028300'})
        self.assertIn('✔️ 현재가:',service.reply('HLB'))
        kr.assert_called_once_with('028300');us.assert_not_called()

    def test_listing_outage_does_not_break_explicit_us(self):
        service,us,kr=self.service({})
        service.codes_loader=Mock(side_effect=OSError('private-detail'))
        self.assertIn('✔️ 현재가:',service.reply('미국 NC'))
        service.codes_loader.assert_not_called()
        self.assertIn('✔️ 현재가:',service.reply('AAPL'))

    def test_collision_counter_uses_listing_and_registered_aliases(self):
        from .verify_market_collisions import collisions
        service,us,kr=self.service({'nc':'KRX:036570','엔씨소프트':'KRX:036570','KB금융':'KRX:105560',
                                    'GS':'KRX:078930','HLB':'KOSDAQ:028300'})
        rows=collisions(service)
        self.assertEqual({r[0] for r in rows},{'NC','KB','GS'})
        self.assertEqual(len(next(r[1] for r in rows if r[0]=='NC')),1)
        us.assert_not_called();kr.assert_not_called()
