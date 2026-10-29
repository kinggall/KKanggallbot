from decimal import Decimal
import unittest
from unittest.mock import Mock

from stockbot.portfolio import PortfolioService
from stockbot.stock_quotes import StockService, QuoteError


def snapshot():
    return dict(schema_version=1,generated_at='2026-10-29T11:00:00Z',quotes_read_at='2026-10-29T10:00:00Z',
                realized=[],holdings=[dict(name='가상회사',ticker='KRX:000001',currency='KRW',
                                          average='120',return_pct='-16.6666667',current_price='100',
                                          quote_at='2026-10-29T10:00:00Z',account='secret-account')])


class PositionTests(unittest.TestCase):
    def test_live_price_and_change_share_one_quote_but_domino_return_is_preserved(self):
        quote=Mock(return_value=dict(price=Decimal('101'),change=Decimal('-2'),percent=Decimal('-1.9417'),fetched_at='2026-10-29T11:01:00Z'))
        service=PortfolioService(snapshot,quote_loader=quote)
        text=service.reply('평단','가상회사')
        self.assertIn('평균 매입가: 120원',text)
        self.assertIn('수익률: -16.67%',text)
        self.assertIn('현재가: 101원',text)
        self.assertIn('전일대비: -2원 (▼1.94%)',text)
        self.assertNotIn('secret-account',text)
        quote.assert_called_once_with('KRX:000001','KRW')

    def test_price_failure_falls_back_to_snapshot_without_making_up_change(self):
        service=PortfolioService(snapshot,quote_loader=Mock(side_effect=OSError('secret-token')))
        text=service.reply('평단','가상회사')
        self.assertIn('현재가: 100원',text)
        self.assertIn('전일대비: 미확인',text)
        self.assertNotIn('secret-token',text)

    def test_alias_matches_held_symbol_and_unknown_holding_does_not_fetch_quotes(self):
        data=snapshot(); data['holdings'][0].update(name='삼성전자',ticker='KRX:005930')
        quote=Mock(return_value={})
        service=PortfolioService(lambda:data,quote_loader=quote)
        self.assertIn('[삼성전자]',service.reply('평단','삼전'))
        quote.reset_mock()
        self.assertIn('없습니다',service.reply('평단','없는회사'))
        quote.assert_not_called()

    def test_structured_domestic_details_validate_and_cache(self):
        loader=Mock(return_value=dict(stck_shrn_iscd='000001',stck_prpr='101',stck_prdy_clpr='100'))
        service=StockService(quote_loader=loader)
        first=service.details('KRX:000001','KRW')
        self.assertEqual(first['price'],Decimal('101'))
        self.assertEqual(first['change'],Decimal('1'))
        self.assertEqual(first['percent'],Decimal('1'))
        first['price']=0
        self.assertEqual(service.details('000001','KRW')['price'],Decimal('101'))
        loader.assert_called_once_with('000001')

    def test_structured_us_details_use_usd_and_do_not_fabricate_previous_close(self):
        loader=Mock(return_value=dict(exchange='NAS',rsym='DNASFAKE',curr='USD',last='10.12'))
        service=StockService(us_loader=loader)
        data=service.details('NASDAQ:FAKE','USD')
        self.assertEqual(data['price'],Decimal('10.12'))
        self.assertIsNone(data['change']);self.assertIsNone(data['percent'])
        with self.assertRaises(QuoteError):service.details('bad input','USD')


if __name__=='__main__':
    unittest.main()
