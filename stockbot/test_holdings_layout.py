from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from stockbot.portfolio import PortfolioService
from stockbot.security_names import USSecurityNames


class HoldingsLayoutTests(unittest.TestCase):
    def test_no_quantity_or_account_and_us_symbol_first(self):
        rows = [dict(name='삼성전자', ticker='KRX:005930', currency='KRW', quantity='80', account='private'),
                dict(name='VOO', ticker='NYSEARCA:VOO', currency='USD', quantity='2', account='secret')]
        names = Mock(return_value='Vanguard S&P 500 ETF')
        service = PortfolioService(name_loader=names)
        text = service.holdings_text(rows, '2026-10-29T11:02:09.852221+00:00')
        self.assertEqual(text, '[보유종목]\n· 삼성전자(005930)\n· VOO(Vanguard S&P 500 ETF)\n\n갱신 일자: 2026-10-29')
        names.assert_called_once_with('VOO')
        for hidden in ('80주', '2주', 'private', 'secret', '보유 수집', '11:02'):
            self.assertNotIn(hidden, text)

    def test_deduplicate_by_symbol_across_accounts_and_convert_date_to_kst(self):
        row = dict(name='가상', ticker='KRX:000001', currency='KRW')
        text = PortfolioService().holdings_text([row, dict(row, account='other')], '2026-10-29T16:00:00Z')
        self.assertEqual(text.count('가상(000001)'), 1)
        self.assertIn('갱신 일자: 2026-10-30', text)

    def test_existing_full_name_does_not_need_network(self):
        names = Mock(side_effect=AssertionError('no external call'))
        text = PortfolioService(name_loader=names).holdings_text([dict(name='Example Fund', ticker='EXAMPLE', currency='USD')], '2026-10-29')
        self.assertIn('EXAMPLE(Example Fund)', text)
        names.assert_not_called()

    def test_public_directory_cached_and_failure_does_not_hide_holdings(self):
        response = Mock()
        response.content = b'Nasdaq Traded|Symbol|Security Name|Test Issue\nY|VOO|Vanguard S&P 500 ETF|N\nY|TEST|Test|Y\n'
        clock = [0]
        names = USSecurityNames(lambda: clock[0])
        with patch('stockbot.security_names.requests.get', return_value=response) as get:
            self.assertEqual(names('VOO'), 'Vanguard S&P 500 ETF')
            self.assertEqual(names('TEST'), '종목명 미확인')
            get.assert_called_once()
        clock[0] = 86401
        import requests
        with patch('stockbot.security_names.requests.get', side_effect=requests.Timeout):
            self.assertEqual(names('VOO'), 'Vanguard S&P 500 ETF')
            text = PortfolioService(name_loader=names).holdings_text([dict(name='FAKE',ticker='NAS:FAKE',currency='USD')], '2026-10-29')
            self.assertIn('FAKE(종목명 미확인)', text)


if __name__ == '__main__':
    unittest.main()
