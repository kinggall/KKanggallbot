import json
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

import touch_attacks as touches

ROOT=Path(__file__).resolve().parents[1]


class TouchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bot
        cls.bot=bot
        cls.data=json.loads(touches.DATA.read_text(encoding='utf-8'))
        cls.groups={g['id']:g for g in cls.data['groups']}

    def reply(self, query):
        return touches.format_reply(query, self.bot.kanlog_ship_ids)

    def test_overview_lists_kinds_without_fetching_or_resolving(self):
        with patch('requests.get',side_effect=AssertionError('Commands are offline')):
            text=touches.format_reply('!터치',lambda _: self.fail('Overview must not resolve'))
        self.assertEqual(text.count('■ '),8)
        for group in self.groups.values():
            ships, separator, description = group['overview'].partition(' — ')
            self.assertIn('· ' + ships, text)
            if separator:
                self.assertNotIn('\n  ' + description, text)
            self.assertNotIn(group['command_example'],text)
        self.assertEqual(text.count('\n\n■ '),8)
        self.assertNotIn(' — ',text)
        self.assertNotIn('2척 터치',text)
        self.assertNotIn('1·3·5번함 공격',text)

    def test_catalog_ids_resolve_to_current_ship_rows(self):
        self.assertEqual(len(self.groups),8)
        for group in self.groups.values():
            self.assertTrue(group['flagship_ids'])
            for sid in group['flagship_ids']+group['related_ship_ids']:
                self.assertIn(sid,self.bot.SHIP_BY_GAME_ID)
            self.assertTrue(all(url.startswith('https://') for url in group['sources']))

    def test_yamato_and_musashi_aliases_keep_two_and_three_ship_rules(self):
        for query in ('야마토','무사시','누사시','大和'):
            text=self.reply('!터치 '+query)
            self.assertIn('야마토형 특수공격',text)
            self.assertIn('×1.9375',text)
            self.assertIn('제4진형',text)
            self.assertIn('야마토·이세·휴가 │ ×1.65 / ×1.575 / ×1.65',text)
            self.assertIn('×1.1 (3척 터치의 3번함 제외)',text)
            self.assertIn('무사시 개2 ※ │ 나가토 개2 / 무츠 개2',text)
            self.assertIn('순서 고정',text)
        self.assertEqual(self.groups['yamato']['attack_order']['two'],[1,1,2])
        self.assertEqual(self.groups['yamato']['attack_order']['three'],[1,2,3])

    def test_mutsu_prioritizes_flagship_and_lists_named_related_touches(self):
        text=self.reply('!터치 무츠')
        self.assertIn('나가토형 일제사격 · 기함 가능',text)
        self.assertIn('야마토형 특수공격 · 특정 조합의 참여함',text)
        self.assertLess(text.index('■ 나가토형'),text.index('■ 야마토형'))
        self.assertIn('×2.6082',text)
        self.assertEqual(Decimal('1.68')*Decimal('1.35')*Decimal('1.15'),Decimal('2.6082'))

    def test_role_specific_multiplier_information(self):
        nelson=self.reply('!터치 로드니')
        self.assertIn('×2.875',nelson)
        colorado=self.reply('!터치 메릴랜드')
        self.assertIn('로드니는 보정 대상 아님',colorado)
        self.assertEqual(self.groups['nelson']['attack_order'],[1,3,5])
        self.assertEqual(self.groups['colorado']['attack_order'],[1,2,3])
        kongo=self.reply('!터치 콩고')
        self.assertIn('×2.756·×2.862',kongo)
        self.assertIn('출격당 최대 3회',kongo)
        self.assertIn('중파까지 가능',kongo)
        self.assertEqual(Decimal('2.6')*Decimal('1.06'),Decimal('2.756'))
        self.assertEqual(Decimal('2.7')*Decimal('1.06'),Decimal('2.862'))
        for query,title in [('리슐리외','프랑스함'),('밸리언트','영국함'),('진게이','잠수함대')]:
            self.assertIn(title,self.reply('!터치 '+query))

    def test_unknown_and_all_existing_named_ship_queries(self):
        self.assertIn('찾지 못했습니다',self.reply('!터치 없는함선'))
        for group in self.groups.values():
            text=self.reply(group['command_example'])
            self.assertIn(group['title'],text)
            self.assertIn('출처:',text)
            self.assertLess(len(text),12000)

    def test_webhook_and_initial_alias_send_only_one_text_message(self):
        for command in ('!터치','!터치 무츠','!ㅌㅊ 야마토'):
            with self.subTest(command=command),patch.object(self.bot.requests,'post') as post:
                response=self.bot.app.test_client().post('/webhook',json={'msg':command,'room':'Test','sender':'Tester','json':{'chat_id':'987'}})
                self.assertEqual(response.status_code,200)
                self.assertEqual(post.call_count,1)
                payload=post.call_args.kwargs['json']
                self.assertEqual(payload['room'],'987')
                self.assertEqual(payload['type'],'text')
                self.assertIn('터치',payload['data'])
