"""Help aliases return the same KakaoTalk reply as the original command."""
import unittest
from unittest.mock import patch

import requests


class HelpAliasTests(unittest.TestCase):
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
