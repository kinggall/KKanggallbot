import re
import unittest
from unittest.mock import patch
import command_aliases


class AliasTests(unittest.TestCase):
    def test_only_twenty_four_main_help_commands_are_aliased(self):
        import bot
        help_commands=set(re.findall(r'![가-힣]+',bot.COMMANDS['!도움말']))
        self.assertEqual(set(command_aliases.ALIASES.values()),help_commands)
        self.assertEqual(len(command_aliases.ALIASES),24)
        for short,full in command_aliases.ALIASES.items():
            self.assertEqual(command_aliases.expand(short),full)
            self.assertEqual(command_aliases.expand(short+' 검색어  두칸'),full+' 검색어  두칸')

    def test_exact_command_token_and_preserve_query(self):
        for source,target in [('!ㅋㅈㅈㅅ','!퀴즈점수'),('!ㄱㄹ 55 중앙','!공략 55 중앙'),
                              ('!ㅈㄷ 뽀이','!정답 뽀이'),('!ㅇㅁ\tB44','!임무 B44'),
                              ('!ㅈㄱ 해역','!전과 해역')]:
            self.assertEqual(command_aliases.expand(source),target)
        for source in ['ㅋㅈ','!ㅋㅈ추가','!ㅈㄷ뽀이','!임무 ㄱㄹ']:
            self.assertEqual(command_aliases.expand(source),source)

    def test_stock_and_hidden_commands_stay_unchanged(self):
        for source in ['!주갤','!주가 삼전','!금리','!보유','!실현 애플','!국내지수',
                       '!수급','!나선','!야선','!환율','!상품','!코인','!미국지수',
                       '!히든','!미르야','!월간원정','!단발퀘','!개구리야',
                       '!왕갤','!깡갤봇','!왕갤아내','!유다치팬티',
                       '!ㅎㄷ','!ㅁㄹㅇ','!ㅂㅇ','!ㅎㅇ']:
            self.assertEqual(command_aliases.expand(source),source)

    def test_webhook_quiz_arguments_and_public_commands(self):
        import bot
        with patch.object(bot.ship_quiz,'service') as service,patch.object(bot.requests,'post') as post:
            service.return_value.handle.return_value='퀴즈 답변'
            client=bot.app.test_client()
            for source,target in [('!ㅋㅈ','!퀴즈'),('!ㅋㅈㅈㅅ','!퀴즈점수'),('!ㅈㄷ 뽀이','!정답 뽀이')]:
                result=client.post('/webhook',json={'msg':source,'sender':'테스터','json':{'chat_id':'room','user_id':'123'}})
                self.assertEqual(result.status_code,200)
                self.assertEqual(service.return_value.handle.call_args.args[0],target)
            client.post('/webhook',json={'msg':'!ㄱㅈ','json':{'chat_id':'room'}})
            self.assertEqual(post.call_args.kwargs['json']['data'],'https://kgbot.pages.dev/')
        with patch.object(bot.guide_lookup,'build_preview',return_value=('공략',[])) as preview,patch.object(bot.requests,'post'),patch.object(bot.IMAGE_SEND_EXECUTOR,'submit',side_effect=lambda fn:fn()):
            bot.app.test_client().post('/webhook',json={'msg':'!ㄱㄹ 55 중앙','json':{'chat_id':'room'}})
            self.assertEqual(preview.call_args.args[0].strip(),'55 중앙')
