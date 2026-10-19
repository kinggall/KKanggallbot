"""Expedition constraints, source differences and every command response."""
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import requests
import expeditions

ROOT = Path(__file__).resolve().parents[1]


class ExpeditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = expeditions.ExpeditionCatalog(ROOT)

    def test_e1_matches_agreed_response_exactly(self):
        self.assertEqual(self.catalog.reply('E1'), '''E1: 라바울방면함대진출(월간/교전2형)
○ 소요시간 - 7시간 30분

[편성조건]
· 중순1(기함) 경순1 구축3 (총 6척)
· 기함 Lv55 / 함대 Lv 합 290
· 화력 450/대공 350/대잠 330/색적 250

[보상]
· 탄약 600/강재 600/보키 1000
· 나사 0~1 / 가구함(대) 0~2

[선행조건]
원정 40''')

    def test_all_63_views_are_offline_complete_and_case_insensitive(self):
        with patch.object(requests, 'get', side_effect=AssertionError('No GET during expedition queries')):
            self.assertEqual(set(self.catalog.items), expeditions.EXPECTED_CODES)
            for code, data in self.catalog.items.items():
                with self.subTest(code=code):
                    output = self.catalog.reply(code)
                    self.assertEqual(output, self.catalog.reply(' ' + code.lower() + ' '))
                    self.assertTrue(output.startswith(code + ': '))
                    for section in ('[편성조건]', '[보상]', '[선행조건]'):
                        self.assertEqual(output.count(section), 1)
                    self.assertIn('○ 소요시간 - ', output)
                    self.assertNotRegex(output, r'[ぁ-んァ-ヶ一-龯]')
                    self.assertNotIn('None', output)
                    self.assertNotIn(' - 0시간', output)
                    self.assertLess(len(output), 1500)
                    self.assertEqual('(월간' in output, data['monthly'])
                    for rule in data['unlocks']['all_of']:
                        self.assertIn(rule['code'], output.split('[선행조건]\n')[1])
                    for stat, value in data['stats'].items():
                        self.assertIn(dict(expeditions.STAT_NAMES)[stat] + ' ' + str(value), output)

    def test_all_of_and_ditto_prerequisites_are_preserved(self):
        self.assertTrue(self.catalog.reply('4').endswith('원정 2 + 3'))
        self.assertTrue(self.catalog.reply('5').endswith('원정 2 + 3'))
        self.assertTrue(self.catalog.reply('14').endswith('원정 11 + 12 + 13'))
        self.assertTrue(self.catalog.reply('A2').endswith('원정 8 + A1'))
        self.assertTrue(self.catalog.reply('A5').endswith('원정 A4 + B3 (매월)'))
        self.assertTrue(self.catalog.reply('23').endswith('해역 1-5 + 원정 22'))
        self.assertTrue(self.catalog.reply('1').endswith('임무 A4'))
        self.assertTrue(self.catalog.reply('44').endswith('원정 40 + 41 (최초)\n원정 A4 (매월)'))

    def test_required_drums_not_confused_with_great_success_drums(self):
        self.assertIn('드럼통 총 8개 / 4척 이상 장착', self.catalog.reply('38'))
        self.assertIn('드럼통 총 6개 / 3척 이상 장착', self.catalog.reply('44'))
        self.assertIn('드럼통 총 4개 / 3척 이상 장착', self.catalog.reply('37'))
        self.assertNotIn('드럼통 총', self.catalog.reply('24'))
        self.assertNotIn('드럼통 총', self.catalog.reply('40'))

    def test_alternative_fleets_and_minimum_counts_are_preserved(self):
        four = self.catalog.reply('4')
        self.assertIn('(최소 3척)', four)
        self.assertIn('· 또는 구축1 해방3', four)
        self.assertIn('호위항모1 (구축2 또는 해방2)', four)
        forty_three = self.catalog.reply('43')
        self.assertIn('호위항모1(기함) (구축2 또는 해방2)', forty_three)
        self.assertIn('· 또는 경항모1(기함) 경순1 (구축+해방)4', forty_three)
        self.assertIn('(수모2 또는 수모1 항모1)', self.catalog.reply('44'))

    def test_final_values_resolve_documented_source_differences(self):
        self.assertIn('색적 70', self.catalog.reply('D2'))
        self.assertIn('이라코 0~1', self.catalog.reply('D2'))
        self.assertIn('탄약 280', self.catalog.reply('14'))
        self.assertIn('보키 30', self.catalog.reply('10'))
        self.assertNotIn('대공 59', self.catalog.reply('A3'))
        self.assertIn('연료 300/탄약 300/보키 100', self.catalog.reply('40'))
        report = json.loads((ROOT / 'data/expedition_verification.json').read_text(encoding='utf-8'))
        self.assertEqual(set(report['checked']), set(self.catalog.items))
        self.assertEqual(len(report['differences']), 18)

    def test_all_items_and_metadata_match_archived_game_master(self):
        report = json.loads((ROOT / 'data/expedition_crosscheck.json').read_text(encoding='utf-8'))
        self.assertEqual(set(report['records']), set(self.catalog.items))
        for code, record in report['records'].items():
            with self.subTest(code=code):
                data = self.catalog.items[code]
                master = record['game_master']
                self.assertEqual({item['type']: item['max'] for item in data['items']}, master['item_maximums'])
                for field in ('minutes', 'monthly', 'combat_type'):
                    self.assertEqual(data[field], master[field])
                for key, level in zip(('fuel', 'ammo', 'steel', 'bauxite'), master['resource_levels']):
                    self.assertEqual(bool(data['resources'][key]), bool(level))
                self.assertEqual(data['resources'], record['KC3']['resources'])

    def test_cross_source_corrections_and_actual_reward_evidence(self):
        self.assertIn('탄약 70', self.catalog.reply('17'))
        self.assertIn('보키 100', self.catalog.reply('18'))
        self.assertIn('탄약 20/보키 100', self.catalog.reply('23'))
        self.assertIn('강재 10', self.catalog.reply('B1'))
        self.assertIn('가구함(중) 0~1', self.catalog.reply('29'))
        self.assertIn('탄약 30/강재 300', self.catalog.reply('39'))
        self.assertIn('가구함(대) 0~1', self.catalog.reply('39'))
        self.assertEqual(280 * 1.5 * 1.2, 504)
        corrections = json.loads((ROOT / 'data/expedition_corrections.json').read_text(encoding='utf-8'))
        self.assertEqual(len(corrections['changes']), 9)
        for change in corrections['changes']:
            selected = self.catalog.items[change['code']]
            for field in change['path']:
                selected = selected[field]
            self.assertEqual(selected, change['after'])

    def test_durations_support_expeditions_and_bad_inputs(self):
        self.assertIn('80시간', self.catalog.reply('26'))
        self.assertIn('· 보상 없음(지원함대)', self.catalog.reply('33'))
        self.assertIn('· 보상 없음(지원함대)', self.catalog.reply('34'))
        self.assertEqual(self.catalog.reply('01'), self.catalog.reply('1'))
        for query in ('', '0', '00', '47', 'A7', 'C1', 'E3', '#38', 'B4 extra', '이세'):
            self.assertEqual(self.catalog.reply(query), expeditions.USAGE, query)

    def test_every_webhook_reply_goes_to_original_room_without_get(self):
        with patch.object(requests, 'get', side_effect=requests.RequestException('offline test')):
            import bot
        self.assertIn('!원정 [번호]', bot.COMMANDS['!도움말'])
        self.assertNotIn('!월간원정', bot.COMMANDS['!도움말'])
        self.assertIn('!월간원정', bot.COMMANDS)
        with (patch.object(requests, 'get', side_effect=AssertionError('No network lookup')),
              patch.object(requests, 'post') as post,
              patch('builtins.print')):
            for code in self.catalog.items:
                post.reset_mock()
                response = bot.app.test_client().post('/webhook', json={
                    'msg': '!원정 ' + code.lower(), 'json': {'chat_id': 'expedition-test'},
                })
                self.assertEqual(response.status_code, 200)
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['json'], {
                    'type': 'text', 'room': 'expedition-test', 'data': self.catalog.reply(code),
                })
