import unittest
from unittest.mock import Mock

from stockbot.aliases import DOMESTIC_GROUPS
from stockbot.stock_quotes import StockService


def output(code):
    return dict(stck_shrn_iscd=code, stck_prpr='100')


class DomesticNicknameTests(unittest.TestCase):
    def service(self, listing):
        quote, us = Mock(side_effect=output), Mock()
        service = StockService(codes_loader=lambda:listing, quote_loader=quote,
                               us_loader=us, basic_loader=lambda c:{})
        return service, quote, us

    def test_every_new_nickname_resolves_against_listing_names(self):
        for aliases, targets in DOMESTIC_GROUPS:
            for alias in aliases:
                with self.subTest(alias=alias):
                    service, quote, us = self.service({targets[0]:'KRX:000001'})
                    self.assertIn('✔️ 현재가:', service.reply(alias))
                    quote.assert_called_once_with('000001'); us.assert_not_called()

    def test_ambiguous_and_real_name_collisions_show_choices(self):
        for alias, names in [('삼엔',('삼성E&A','에스엠')),('HD현중',('HD한국조선해양','HD현대중공업')),
                             ('코스모',('코스모신소재','코스모화학')),('네패스',('네패스','네패스아크')),
                             ('원익',('원익','원익IPS')),('신한',('신한','신한지주'))]:
            with self.subTest(alias=alias):
                service, quote, us = self.service({names[0]:'KRX:000001',names[1]:'KRX:000002'})
                text = service.reply(alias)
                self.assertIn('여러 종목',text)
                for name in names:self.assertIn(name,text)
                quote.assert_not_called(); us.assert_not_called()

    def test_preferred_alias_requires_real_listed_preferred_share(self):
        for alias in ('삼전우','삼전 우','삼성전자우'):
            service, quote, _ = self.service({'삼성전자':'KRX:005930','삼성전자우':'KRX:005935'})
            service.reply(alias); quote.assert_called_once_with('005935')
        service, quote, _ = self.service({'우리금융지주':'KRX:316140'})
        self.assertIn('없습니다',service.reply('우금지우'))
        quote.assert_not_called()

    def test_multiple_preferred_classes_are_not_arbitrarily_selected(self):
        service, quote, _ = self.service({'현대차':'KRX:005380','현대차우':'KRX:005385',
                                          '현대차2우B':'KRX:005387','현대차3우B':'KRX:005389'})
        text = service.reply('현차우')
        for name in ('현대차우','현대차2우B','현대차3우B'):self.assertIn(name,text)
        quote.assert_not_called()

    def test_real_company_name_ending_in_woo_is_never_stripped(self):
        service, quote, _ = self.service({'가상우':'KRX:000001','가상우우':'KRX:000002'})
        service.reply('가상우'); quote.assert_called_once_with('000001')

    def test_unknown_or_renamed_listing_never_uses_a_guessed_code(self):
        service, quote, _ = self.service({'다른회사':'KRX:000001'})
        self.assertIn('없습니다',service.reply('삼바'))
        quote.assert_not_called()
        service, quote, _ = self.service({'삼성E&A':'KRX:028050'})
        service.reply('삼엔'); quote.assert_called_once_with('028050')


if __name__ == '__main__':
    unittest.main()
