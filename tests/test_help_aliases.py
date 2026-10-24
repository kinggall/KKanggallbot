"""Help aliases return the same KakaoTalk reply as the original command."""
import unittest
from unittest.mock import patch

import requests


class HelpAliasTests(unittest.TestCase):
    def test_fold_hint_and_grouped_commands_preserve_help_content(self):
        import bot
        text=bot.COMMANDS['!도움말']
        self.assertTrue(text.startswith('[깡갤봇 사용법]'+'\u200b'*4000+'\n\n'))
        self.assertEqual(text.count('\u200b'),4000)
        visible=text.replace('\u200b','')
        for category in ['공지 · 안내','임무 · 출격','함선 · 육성','장비 · 공창','원정 · 전과']:
            self.assertIn('━━━━ '+category+' ━━━━',visible)
        for command in ['!공지','!통합공략','!반복퀘','!멘테','!이벤트','!전과','!드랍','!한정드랍','!칸무스','!슬롯','!초기장비','!경험치','!피트','!장비','!개발','!레시피','!개수','!원정','!신규임무','!임무','!공략']:
            self.assertEqual(visible.count(command),1,command)
        for hidden in ['!월간원정','!단발퀘','!개구리야','!미르야','팬티','아내']:
            self.assertNotIn(hidden,visible)
        self.assertNotIn('판당경험치',visible)
        self.assertTrue(visible.endswith('https://kgbot.pages.dev/'))
        self.assertLess(len(text.encode('utf-8')),16000)

    def test_help_aliases_send_identical_reply(self):
        with patch.object(requests, 'get', side_effect=requests.RequestException('offline test')):
            import bot
        for command in ('!도움말', '!도움', '!명령어', '!명령'):
            with self.subTest(command=command), patch.object(bot.requests, 'post') as post:
                response = bot.app.test_client().post('/webhook', json={
                    'msg': command, 'json': {'chat_id': 'help-test'},
                })
                self.assertEqual(response.status_code, 200)
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['json']['data'], bot.COMMANDS['!도움말'])
                self.assertEqual(post.call_args.kwargs['json']['room'], 'help-test')
