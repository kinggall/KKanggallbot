import unittest
from unittest.mock import Mock,patch
from stockbot import stock_commands


class Inline:
    def submit(self,callback):callback()


class StockCommandTests(unittest.TestCase):
    def test_command_routes_to_its_own_module_and_original_room(self):
        import bot
        with patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.SERVICE,'reply',return_value='가상 주가') as reply,patch.object(stock_commands.requests,'post') as post:
            response=bot.app.test_client().post('/webhook',json={'msg':'!주가 가상회사','json':{'chat_id':'stock-room'}})
        self.assertEqual(response.status_code,200);reply.assert_called_once_with('가상회사')
        self.assertEqual(post.call_args.kwargs['json'],{'type':'text','room':'stock-room','data':'가상 주가'})

    def test_investment_help_uses_its_own_menu_without_quote_lookup(self):
        with patch.object(stock_commands, 'EXECUTOR', Inline()), patch.object(stock_commands.SERVICE, 'reply') as reply, patch.object(stock_commands.requests, 'post') as post:
            result = stock_commands.handle('!주갤', 'investment-room', 'http://local/reply')
        self.assertEqual(result[1], 200)
        self.assertEqual(post.call_args.kwargs['json']['room'], 'investment-room')
        self.assertEqual(post.call_args.kwargs['json']['data'], stock_commands.INVESTMENT_HELP)
        reply.assert_not_called()

    def test_help_alias_is_identical_and_never_loads_private_data(self):
        import bot
        for command in ('!주갤',):
            with self.subTest(command=command), patch.object(stock_commands, 'EXECUTOR', Inline()), patch.object(stock_commands.SERVICE, 'reply') as quote, patch.object(stock_commands.PORTFOLIO, 'reply') as portfolio, patch.object(stock_commands.requests, 'post') as post:
                response = bot.app.test_client().post('/webhook', json={'msg':command, 'room':'help-room'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(post.call_args.kwargs['json']['data'], stock_commands.INVESTMENT_HELP)
                quote.assert_not_called(); portfolio.assert_not_called()

    def test_help_layout_matches_kancolle_fold_style(self):
        text = stock_commands.INVESTMENT_HELP
        self.assertTrue(text.startswith('[주갤봇 사용법]' + '\u200b' * 4000 + '\n\n'))
        self.assertEqual(text.count('\u200b'), 4000)
        for section in ('주가 · 시세', '보유 · 평가', '실현 · 손익'):
            self.assertIn('━━━━ ' + section + ' ━━━━', text)
        for command in ('!주가', '!보유', '!실현'):
            self.assertIn(command, text)
        self.assertNotIn('!수익률', text)
        self.assertNotIn('!평단', text)
        self.assertNotIn('!투자', text)
        self.assertIn('!실현 [종목명/티커]', text)
        self.assertIn('보유 · 평가 및 실현 · 손익 종목은 정달봄의 실제 거래 기록입니다.', text)

    def test_removed_commands_do_not_query_or_send(self):
        with patch.object(stock_commands.SERVICE,'reply') as quote, patch.object(stock_commands.PORTFOLIO,'reply') as portfolio, patch.object(stock_commands.requests,'post') as post:
            for command in ('!투자', '!수익률', '!수익률 삼성전자', '!평단', '!평단 롯데쇼핑'):
                self.assertIsNone(stock_commands.handle(command,'room','http://local/reply'))
        quote.assert_not_called(); portfolio.assert_not_called(); post.assert_not_called()

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
            for text in ('🔵 가상회사 주가 🔵','!도움말','!주가아님','!주갤아님','!주갤 추가','일반 대화'):
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
