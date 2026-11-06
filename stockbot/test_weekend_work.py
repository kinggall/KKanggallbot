import unittest
from unittest.mock import patch
from . import weekend_work, stock_commands


class WeekendWorkTests(unittest.TestCase):
    def test_example(self):
        text = weekend_work.render('-40422926')
        self.assertEqual(text, '✔️ 주말출근: 13.5년')

    def test_rounding_and_zero(self):
        self.assertEqual(weekend_work.render('-150000'), '✔️ 주말출근: 0.1년')
        self.assertEqual(weekend_work.render('-150001'), '✔️ 주말출근: 0.1년')
        self.assertEqual(weekend_work.render('0'), '✔️ 주말출근: 0년')
        self.assertEqual(weekend_work.render('-30000000'), '✔️ 주말출근: 10년')
        self.assertEqual(weekend_work.render('-20000000'), '✔️ 주말출근: 6.7년')
        self.assertEqual(weekend_work.render('1'), '✔️ 주말출근: 왜 함?')
        self.assertNotIn('10.0', weekend_work.render('-30000000'))

    def test_html(self):
        html = '<script>총투자수익 999원</script><div>총투자수익</div><b>-40,422,926<span>원</span></b>'
        self.assertEqual(weekend_work.overview_profit(html), -40422926)
        with self.assertRaises(ValueError):
            weekend_work.overview_profit('평가손익 -99원')
        with self.assertRaises(ValueError):
            weekend_work.overview_profit('총투자수익 1원 총투자수익 2원')

    def test_failure_no_fallback_or_private_error(self):
        def fail():
            raise RuntimeError('secret')
        self.assertNotIn('secret', weekend_work.reply(fail))

    def test_routing(self):
        class Inline:
            def submit(self, fn):
                fn()
        with patch.object(stock_commands, 'EXECUTOR', Inline()), patch.object(weekend_work, 'reply', return_value='✔️ 주말출근: 왜 함?'), patch.object(stock_commands.requests, 'post') as post:
            self.assertEqual(stock_commands.handle('!주말출근', 'room', 'http://local/reply')[1], 200)
            self.assertEqual(post.call_args.kwargs['json']['data'], '✔️ 주말출근: 왜 함?')
