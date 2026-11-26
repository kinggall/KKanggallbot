import json
from decimal import Decimal
import unittest
from unittest.mock import patch
import saury


class SauryTests(unittest.TestCase):
    def test_screenshot_rates_and_complete_unique_nodes(self):
        data=json.loads(saury.DATA.read_text(encoding='utf-8'))
        rows={(r['map'],r['node']):r for r in data['rows']}
        self.assertEqual(len(rows),38)
        self.assertEqual(len({r['map'] for r in data['rows']}),14)
        self.assertEqual(rows['6-1','J']['s'],'22.222')
        self.assertEqual(rows['3-2','K']['s'],'56.916')
        self.assertEqual(rows['3-2','K']['a'],'23.234')
        self.assertEqual(rows['1-5','I']['s'],'30.323')
        self.assertEqual(rows['1-1','C']['s'],'1.547')
        for row in rows.values():
            for rank in ('s','a'):
                self.assertTrue(0<=Decimal(row[rank])<=100)

    def test_offline_format_order_year_and_equipment(self):
        with patch('requests.get',side_effect=AssertionError('No command fetch')):
            text=saury.format_reply()
        self.assertIn('✔️ 2024년 기준',text)
        self.assertIn('· 3-2 K: S 56.9% / A 23.2%',text)
        self.assertIn('· 1-1 C: S 1.5% / A 0.0%',text)
        self.assertIn('· 1-1 B: S 3.0% / A 0.0%',text)
        self.assertIn('· 6-1 J: S 22.2% / A 0.0%',text)
        self.assertLess(text.index('· 1-1 C'),text.index('· 1-2 C'))
        self.assertLess(text.index('· 6-5 M'),text.index('· 7-4 H'))
        self.assertLess(text.index('· 7-4 P'),text.index('[꽁치 유리 장비]'))
        for category in ('소나','폭뢰','정찰기·수상폭격기·뇌격기'):
            self.assertIn('· '+category+':',text)
        self.assertIn('폭뢰투사기는 어장에 피해',text)
        self.assertNotIn('2026년 기준',text)

    def test_both_commands_send_one_text_reply(self):
        import bot
        for command in ('!꽁치','!ㄲㅊ'):
            with self.subTest(command=command),patch.object(bot.requests,'post') as post:
                response=bot.app.test_client().post('/webhook',json={'msg':command,'room':'test','sender':'test','chat_id':'123'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(post.call_count,1)
                payload=post.call_args.kwargs['json']
                self.assertEqual(payload['type'],'text')
                self.assertIn('2024년 기준',payload['data'])
