import json
from pathlib import Path
import unittest
from unittest.mock import patch
import senka

class SenkaCommandTests(unittest.TestCase):
    def test_all_current_quest_rewards_choices_and_totals(self):
        text=senka.quest_reply()
        for code in ['Bq2','Bq7','Bq8','Bq10','Bq11','Bq12','Bq13','By9','By10','B170']:
            self.assertEqual(text.count('('+code+')'),1)
        self.assertIn('확정 전과 합계: 2,050',text)
        self.assertIn('확정 전과 합계: 1,080',text)
        self.assertIn('(B170) - 800 (선택)',text)
        self.assertNotIn('2501',text)
        self.assertLess(len(text),2000)
        self.assertEqual(senka.rewards({'choices':[{'category':'senka','amount':800}]}),[(800,True)])

    def test_boss_points_and_gauge_coverage(self):
        text=senka.map_reply()
        self.assertIn('7-1 - S 1.176 / A 0.9408',text)
        self.assertIn('1-1 - S 0.014 / A 0.0112',text)
        self.assertIn('7-2-1 - S 0.252 / A 0.2016',text)
        self.assertIn('7-2-2 - S 1.652 / A 1.3216',text)
        self.assertIn('1-6 - 보스 전투 없음',text)
        for stage in range(1,4):self.assertIn(f'5-6-{stage} - 미확인',text)
        data=json.loads((Path(senka.ROOT)/'data/senka_boss.json').read_text())
        self.assertEqual(len(data['maps']),43)
        self.assertEqual(len({r['area'] for r in data['maps']}),43)
        self.assertEqual(sum(r['admiral_exp_s'] is not None for r in data['maps']),39)
        for row in data['maps']:
            self.assertIn('· '+row['area']+' - ',text)
            self.assertTrue(row['source'].startswith('https://zekamashi.net/'))
            self.assertEqual(len(row['source_sha256']),64)
        self.assertEqual(senka.points(100000),'70')
        self.assertEqual(senka.points(0),'0')
        self.assertEqual(senka.points(1680+3*140),'1.47')
        self.assertLess(len(text),2500)

    def test_new_webhooks_are_offline_and_ranking_is_preserved(self):
        import bot
        client=bot.app.test_client()
        for query,expected in [('임무',senka.quest_reply()),('해역',senka.map_reply()),('',senka.USAGE),('abc',senka.USAGE)]:
            with patch.object(bot.requests,'post') as post,patch.object(bot,'format_senka_ranking',side_effect=AssertionError('Not a ranking query')):
                self.assertEqual(client.post('/webhook',json={'msg':('!전과 '+query).strip(),'json':{'chat_id':'senka-room'}}).status_code,200)
                post.assert_called_once_with(bot.IRIS_REPLY_URL,json={'type':'text','room':'senka-room','data':expected},timeout=10)
        for rank in ['5','20','100','500']:
            with patch.object(bot.requests,'post') as post,patch.object(bot,'format_senka_ranking',return_value='ranking') as ranking:
                self.assertEqual(client.post('/webhook',json={'msg':'!전과 '+rank,'room':'r'}).status_code,200)
                ranking.assert_called_once_with(rank)
                self.assertEqual(post.call_args.kwargs['json']['data'],'ranking')
        self.assertIn('!전과 [5/20/100/500/임무/해역]',bot.COMMANDS['!도움말'])
