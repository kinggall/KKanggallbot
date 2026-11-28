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

    def test_yamato_and_musashi_are_split_by_flagship(self):
        for query in ('야마토','大和'):
            text=self.reply('!터치 '+query)
            self.assertIn('■ 야마토 특수공격',text)
            self.assertNotIn('무사시→야마토',text)
            self.assertNotIn('×1.9375',text)
            self.assertIn('제4진형',text)
            self.assertIn('야마토·이세·휴가 │ ×1.65 / ×1.575 / ×1.65',text)
            self.assertIn('×1.1 (3척 터치의 3번함 제외)',text)
            self.assertIn('무사시 개2(고정) │ 나가토 개2 / 무츠 개2',text)
        for query in ('무사시','누사시'):
            text=self.reply('!터치 '+query)
            self.assertIn('■ 무사시 특수공격',text)
            self.assertIn('×1.9375',text)
            self.assertNotIn('3척',text)
            self.assertNotIn('나가토',text)
            self.assertIn('무사시 개2 │ 야마토 개2/중',text)
            self.assertNotIn('야마토→무사시',text)
        self.assertEqual(self.groups['yamato']['attack_order']['two'],[1,1,2])
        self.assertEqual(self.groups['yamato']['attack_order']['three'],[1,2,3])

    def test_mutsu_only_shows_mutsu_as_flagship(self):
        text=self.reply('!터치 무츠')
        self.assertIn('■ 무츠 일제사격',text)
        self.assertNotIn('야마토',text)
        self.assertNotIn('콜로라도',text)
        self.assertNotIn('나가토 개2→무츠',text)
        self.assertIn('무츠 개2→나가토 개2',text)
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
        for query,title in [('리슐리외','리슐리외'),('밸리언트','밸리언트'),('진게이','진게이')]:
            self.assertIn(title,self.reply('!터치 '+query))

    def test_unknown_and_all_existing_named_ship_queries(self):
        self.assertIn('찾지 못했습니다',self.reply('!터치 없는함선'))
        for group in self.groups.values():
            text=self.reply(group['command_example'])
            self.assertIn('기함 기준]',text)
            self.assertNotIn('출처:',text)
            self.assertNotIn('https://',text)
            self.assertNotIn('※',text)
            self.assertTrue(text.endswith('자료 검수: '+self.data['reviewed_on']))
            self.assertLess(len(text),12000)

    def test_every_flagship_view_is_covered_and_participants_alone_are_not_matched(self):
        for group in self.groups.values():
            ids={sid for view in group['flagship_views'] for sid in view['ship_ids']}
            self.assertEqual(ids,set(group['flagship_ids']))
            for view in group['flagship_views']:
                text=touches.format_reply('!터치 검사',lambda _:set(view['ship_ids']))
                self.assertIn('■ '+view['title'],text)
                self.assertEqual(text.count('■ '),1)
        self.assertIn('찾지 못했습니다',self.reply('!터치 아이오와'))
        overview=self.reply('!터치')
        self.assertIn('!터치 [기함명]',overview)
        self.assertIn('해당 함선을 기함으로 편성했을 때',overview)

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
