import unittest
from unittest.mock import Mock
from datetime import datetime
from .us_quotes import load_daymarket, format_us, PATH, is_daymarket
from .stock_quotes import KST, QuoteError


class DaymarketTests(unittest.TestCase):
    def test_price_and_regular_close(self):
        client = Mock()
        client.query.return_value = dict(rsym='RBAQIREN', curr='USD', last='20.27', base='21.71')
        result = load_daymarket(client, PATH, 'IREN', dict(exchange='NAS', last='18.03'))
        client.query.assert_called_once_with(PATH, {'AUTH': '', 'EXCD': 'BAQ', 'SYMB': 'IREN'})
        reply = format_us(result, 'IREN', datetime(2026, 11, 6, 11, tzinfo=KST))
        self.assertIn('▲12.42%', reply)
        self.assertIn('정규장 종가대비: +2.24 USD', reply)
        self.assertIn('데이마켓', reply)

    def test_wrong_symbol_rejected(self):
        client = Mock()
        client.query.return_value = dict(rsym='RBAQAAPL', curr='USD', last='20.27')
        with self.assertRaises(QuoteError):
            load_daymarket(client, PATH, 'IREN', dict(exchange='NAS', last='18.03'))

    def test_window(self):
        self.assertTrue(is_daymarket(datetime(2026, 11, 6, 11, tzinfo=KST)))
        self.assertFalse(is_daymarket(datetime(2026, 11, 7, 11, tzinfo=KST)))
        self.assertFalse(is_daymarket(datetime(2026, 11, 6, 9, tzinfo=KST)))
