import unittest
from unittest.mock import Mock,patch
import stock_commands


class Inline:
    def submit(self,callback):callback()


class StockCommandTests(unittest.TestCase):
    def test_command_routes_to_its_own_module_and_original_room(self):
        import bot
        with patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.SERVICE,'reply',return_value='가상 주가') as reply,patch.object(stock_commands.requests,'post') as post:
            response=bot.app.test_client().post('/webhook',json={'msg':'!주가 가상회사','json':{'chat_id':'stock-room'}})
        self.assertEqual(response.status_code,200);reply.assert_called_once_with('가상회사')
        self.assertEqual(post.call_args.kwargs['json'],{'type':'text','room':'stock-room','data':'가상 주가'})

    def test_null_iris_metadata_uses_top_level_room(self):
        import bot
        with patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.SERVICE,'reply',return_value='가상 주가'),patch.object(stock_commands.requests,'post') as post:
            response=bot.app.test_client().post('/webhook',json={'msg':'!주가 가상회사','room':'fallback-room','json':None})
        self.assertEqual(response.status_code,200)
        self.assertEqual(post.call_args.kwargs['json']['room'],'fallback-room')

    def test_empty_command_shows_usage_only_when_directly_requested(self):
        with patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.SERVICE,'reply',return_value='사용법') as reply,patch.object(stock_commands.requests,'post'):
            self.assertEqual(stock_commands.handle('!주가','room','http://local/reply')[1],200)
        reply.assert_called_once_with('')

    def test_no_stock_command_is_registered_in_help_or_hidden_list(self):
        import bot
        for key,text in bot.COMMANDS.items():
            self.assertNotIn('!주가',key);self.assertNotIn('!주가',text)

    def test_quote_reply_echo_and_other_commands_are_not_intercepted(self):
        with patch.object(stock_commands.SERVICE,'reply') as reply:
            for text in ('🔵 가상회사 주가 🔵','!도움말','!주가아님','일반 대화'):
                self.assertIsNone(stock_commands.handle(text,'room','http://local/reply'))
        reply.assert_not_called()

    def test_missing_room_does_not_send_any_message(self):
        with patch.object(stock_commands.requests,'post') as post:
            self.assertEqual(stock_commands.handle('!주가 가상회사',None,'http://local/reply')[1],400)
        post.assert_not_called()

    def test_full_queue_gives_a_short_notice_without_releasing_unowned_slot(self):
        semaphore=Mock();semaphore.acquire.return_value=False
        with patch.object(stock_commands,'PENDING',semaphore),patch.object(stock_commands.requests,'post') as post:
            result=stock_commands.handle('!주가 가상회사','room','http://local/reply')
        self.assertTrue(result[0]['stock_queue_busy']);self.assertIn('요청이 많습니다',post.call_args.kwargs['json']['data'])
        semaphore.release.assert_not_called()
