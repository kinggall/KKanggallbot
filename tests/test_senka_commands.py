import json
from pathlib import Path
import unittest
from unittest.mock import patch
import senka

class SenkaCommandTests(unittest.TestCase):
    def test_all_current_quest_rewards_choices_and_totals(self):
        text=senka.quest_reply()
        for code in ['Bq2','Bq7','Bq8','Bq10','Bq11','Bq12','Bq13','By9','By10']:
            self.assertEqual(text.count('('+code+')'),1)
        self.assertIn('확정 전과 합계: 2,050점',text)
        self.assertIn('확정 전과 합계: 1,080점',text)
        self.assertIn('(By9) - 480점',text)
        self.assertTrue(text.startswith('[계간]\n'))
        self.assertNotIn('B170',text)
        self.assertNotIn('[단발]',text)
        self.assertNotIn('전과 임무',text)
        self.assertNotIn('상세:',text)
        self.assertNotIn('※',text)
        self.assertNotIn('2501',text)
        self.assertLess(len(text),2000)
        self.assertEqual(senka.rewards({'choices':[{'category':'senka','amount':800}]}),[(800,True)])

    def test_boss_points_and_gauge_coverage(self):
        text=senka.map_reply()
        self.assertIn('7-1 - S 1.17 / A 0.94',text)
        self.assertIn('1-1 - S 0.01 / A 0.01',text)
        self.assertIn('7-2-1 - S 0.25 / A 0.20',text)
        self.assertIn('7-2-2 - S 1.65 / A 1.32',text)
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
        self.assertEqual(senka.points(100000),'70.00')
        self.assertEqual(senka.points(0),'0.00')
        self.assertEqual(senka.points(1740),'1.21')
        self.assertEqual(senka.points(1680+3*140),'1.47')
        self.assertLess(len(text),2500)

    def test_monthly_eo_rewards_precede_boss_values(self):
        text=senka.map_reply()
        self.assertTrue(text.startswith('[EO 클리어 전과 · 월간]\n'))
        eo,boss=text.split('해역별 보스 전과 (S/A)',1)
        for area,score in [('1-5',75),('1-6',75),('2-5',100),('3-5',150),('4-5',180),('5-5',200),('5-6',225),('6-5',250),('7-5',170)]:
            self.assertIn(f'· {area} - {score}점',eo)
        self.assertIn('EO 전과 합계: 1,425점',eo)
        self.assertIn('1-6 - 보스 전투 없음',boss)
        self.assertIn('5-6-1 - 미확인',boss)
        data=json.loads((Path(senka.ROOT)/'data/senka_boss.json').read_text())
        self.assertEqual(len({r['area'] for r in data['eo_rewards']}),9)
        self.assertEqual(sum(r['points'] for r in data['eo_rewards']),1425)

    def test_new_webhooks_are_offline_and_ranking_is_preserved(self):
        import bot
        client=bot.app.test_client()
        for query,expected in [('임무',senka.quest_reply()),('해역',senka.map_reply()),('',senka.USAGE),('abc',senka.USAGE)]:
            with patch.object(bot.requests,'post') as post,patch.object(bot,'format_senka_ranking',side_effect=AssertionError('Not a ranking query')):
                self.assertEqual(client.post('/webhook',json={'msg':('!전과 '+query).strip(),'json':{'chat_id':'senka-room'}}).status_code,200)
                post.assert_called_once_with(bot.IRIS_REPLY_URL,json={'type':'text','room':'senka-room','data':expected},timeout=10)
        for query,rank in [('5','5'),('20','20'),('100','100'),('500','500'),('연합','5'),('1군','20'),('2군','100'),('3군','500')]:
            with patch.object(bot.requests,'post') as post,patch.object(bot,'format_senka_ranking',return_value='ranking') as ranking:
                self.assertEqual(client.post('/webhook',json={'msg':'!전과 '+query,'room':'r'}).status_code,200)
                ranking.assert_called_once_with(rank)
                self.assertEqual(post.call_args.kwargs['json']['data'],'ranking')
        self.assertEqual(senka.USAGE,'사용법: !전과 [5/20/100/500]\n!전과 임무 / !전과 해역')
        self.assertIn('!전과 [등수/임무/해역]',bot.COMMANDS['!도움말'])
