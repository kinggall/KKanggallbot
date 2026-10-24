import json
from pathlib import Path
import unittest
from unittest.mock import patch
import experience

class ExperienceTests(unittest.TestCase):
    def test_known_totals_and_non_linear_boundaries(self):
        table=experience.levels()
        for level,total in {1:0,2:100,50:122500,80:383000,98:851500,99:1000000,100:1000000,101:1010000,150:4360000,175:10950000,180:13000000,188:20200000}.items():
            self.assertEqual(table[level],total)
        for query,amount in [('1 99','1,000,000'),('80 99','617,000'),('98 99','148,500'),('99 100','0'),('100 101','10,000'),('187 188','1,600,000'),('99 99','0')]:
            self.assertIn('· 필요 경험치: '+amount,experience.reply(query))

    def test_input_validation_and_baseline_notice(self):
        help_text=experience.usage(188)
        for query in ['', '99','1 2 3 4','0 99','1 189','-1 99','1.5 99','1 1e2','1 99999999','Lv1 Lv99','1/99','하나 99']:
            self.assertEqual(experience.reply(query),help_text,query)
        self.assertIn('목표 레벨은 현재 레벨 이상',experience.reply('99 1'))
        self.assertEqual(experience.reply('  1   99  '),'Lv1 → Lv99\n· 필요 경험치: 1,000,000')
        self.assertNotIn('결혼',experience.reply('1 99'))
        self.assertIn('결혼(가)',experience.reply('99 100'))
        self.assertIn('결혼(가)',experience.reply('1 188'))
        self.assertNotIn('결혼',experience.reply('100 188'))

    def test_optional_per_run_rounds_up_without_float(self):
        self.assertEqual(experience.reply('80 99 1500'),'Lv80 → Lv99\n· 필요 경험치: 617,000\n· 판당 경험치: 1,500\n· 필요 횟수: 412회')
        for query,expected in [('80 99 1500','412'),('1 2 25','4'),('1 2 30','4'),('1 2 1000','1'),('99 99 1500','0'),('99 100 1500','0'),('1 188 1','20,200,000')]:
            self.assertIn('· 필요 횟수: '+expected+'회',experience.reply(query),query)
        self.assertIn('· 판당 경험치: 1,500',experience.reply('80 99 1500'))
        self.assertIn('결혼(가)',experience.reply('99 100 1500'))
        self.assertNotIn('필요 횟수',experience.reply('80 99'))
        for value in ['0','-1','1.5','1e3','1,500','abc','9'*19]:
            self.assertIn('판당 경험치는 1 이상의 정수',experience.reply('80 99 '+value))

    def test_whole_table_and_all_interval_additivity(self):
        rows=json.loads((Path(experience.ROOT)/'data/ship_experience.json').read_text())['levels']
        self.assertEqual(len(rows),188)
        for a,b in zip(rows,rows[1:]):self.assertEqual(b[1]-a[1],a[2])
        for start in range(1,189):
            for target in range(start,189):
                self.assertEqual(sum(r[2] for r in rows[start-1:target-1]),experience.levels()[target]-experience.levels()[start])

    def test_webhook_and_help(self):
        import bot
        self.assertIn('!경험치 [현재레벨] [목표레벨]\n',bot.COMMANDS['!도움말'])
        self.assertNotIn('판당경험치',bot.COMMANDS['!도움말'])
        client=bot.app.test_client()
        for query in ['!경험치 1 99','!경험치','!경험치 99 1','!경험치 99 100','!경험치 80 99 1500','!경험치 80 99 0']:
            with patch.object(bot.requests,'post') as post:
                response=client.post('/webhook',json={'msg':query,'room':'fallback','json':{'chat_id':'experience-room'}})
                self.assertEqual(response.status_code,200)
                post.assert_called_once_with(bot.IRIS_REPLY_URL,json={'type':'text','room':'experience-room','data':experience.reply(query[len('!경험치'):])},timeout=10)
        with patch.object(bot.experience,'reply',side_effect=ValueError('bad data')),patch.object(bot.requests,'post') as post:
            self.assertEqual(client.post('/webhook',json={'msg':'!경험치 1 99','room':'room'}).status_code,200)
            self.assertEqual(post.call_args.kwargs['json']['data'],'경험치 데이터를 불러오지 못했습니다.')
