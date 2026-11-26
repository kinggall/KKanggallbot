import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quests import QuestCatalog
from scripts.collect_new_quests import PAGE, read_source

ROOT = Path(__file__).resolve().parents[1]


class NovemberQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = QuestCatalog(ROOT)
        cls.update = json.loads((ROOT / 'data/quest_november_updates.json').read_text())

    def test_only_six_latest_quests_and_no_sortie_guide_example(self):
        text = self.catalog.new_quests_reply()
        self.assertIn('2026-11-24 점검 신규 임무 (6개)', text)
        for code in ('2611 B1', '2611 B2', '2611 B3', '2611 Cw3', '2611 F1', '2611 F2'):
            self.assertIn(code + ':', text)
        self.assertNotIn('2610', text)
        self.assertNotIn('!공략', text)

    def test_eo_identities_and_wiki_aliases_return_same_records(self):
        for api_id, canonical, wiki in ((381, '2611 Cw1', '2611 C1'),
                                        (386, '2611 Cw2', '2611 C2'), (1172, 'F144', 'F144')):
            self.assertEqual(self.catalog.items[str(api_id)]['wiki_id'], canonical)
            for query in (canonical, canonical.replace(' ', ''), wiki, wiki.replace(' ', '')):
                self.assertEqual(self.catalog.reply(query), self.catalog.detail(str(api_id)))

    def test_exercise_ranks_flagship_and_weekly_frequency(self):
        first, second = (self.catalog.items[k] for k in ('381', '386'))
        self.assertEqual((first['frequency'], second['frequency']), ('weekly', 'weekly'))
        self.assertTrue(first['limited'] and second['limited'])
        self.assertEqual((first['requirements']['result'], first['requirements']['times']), ('A', 3))
        self.assertEqual((second['requirements']['result'], second['requirements']['times']), ('S', 3))
        self.assertIn('기함 포함', self.catalog.detail('386'))
        self.assertNotIn('기함 포함', self.catalog.detail('381'))
        self.assertIn('381', self.catalog.search_keys('하츠즈키'))
        self.assertIn('386', self.catalog.search_keys('아케보노'))

    def test_factory_preserves_destruction_and_two_guaranteed_max_torpedoes(self):
        row = self.catalog.items['1172']
        self.assertEqual(row['frequency'], 'onetime')
        self.assertFalse(row['limited'])
        text = self.catalog.detail('1172')
        for phrase in ('1·2번 슬롯', '3번 슬롯', '사연장어뢰 x10', '개발자재 x60', '신형병장자재 x2',
                       '공창자원 x2', '★MAX는 소멸', '오연장(산소)어뢰 ★10 x2'):
            self.assertIn(phrase, text)
        rewards = row['rewards']['other']
        self.assertEqual(rewards[0]['choices'][1]['stars'], 4)
        self.assertEqual((rewards[1]['stars'], rewards[1]['amount']), (10, 2))

    def test_only_known_prerequisites_are_linked_and_uncertainty_retained(self):
        for api_id, prerequisite in (('381', 'Cd1'), ('386', 'Bd5'), ('1172', 'Fd5')):
            row = self.catalog.items[api_id]
            self.assertTrue(row['prerequisite_incomplete'])
            self.assertTrue(row['prereqs_unverified'])
            self.assertEqual([self.catalog.codes[str(i)] for i in row['prereqs']], [prerequisite])

    def test_har_cached_304_with_body_is_read_but_empty_or_error_entry_is_rejected(self):
        body = '<html>cached quest page</html>'
        entry = {'request': {'url': PAGE}, 'response': {'status': 304, 'content': {'text': body}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page.har'
            for status, content, valid in ((304, body, True), (304, '', False), (403, body, False)):
                entry['response'].update(status=status, content={'text': content})
                path.write_text(json.dumps({'log': {'entries': [entry]}}))
                if valid:
                    self.assertEqual(read_source(path), body)
                else:
                    with self.assertRaises(ValueError):
                        read_source(path)

    def test_rendered_response_never_needs_network(self):
        import bot
        with patch.object(bot.requests, 'get', side_effect=AssertionError('offline')), patch.object(bot.requests, 'post') as send:
            result = bot.app.test_client().post('/webhook', json={'msg': '!신규임무', 'json': {'chat_id': 'room'}})
            self.assertEqual(result.status_code, 200)
            self.assertIn('신규 임무 (6개)', send.call_args.kwargs['json']['data'])

    def test_saury_factory_codes_do_not_overwrite_permanent_torpedo_quest(self):
        self.assertIn('새 꽁치를 맛있게', self.catalog.reply('2611F1'))
        self.assertIn('국지전투기 신덴', self.catalog.reply('2611F2'))
        self.assertIn('야전 돌격 장비', self.catalog.reply('F144'))
        self.assertIn('시제 신덴(국지전투기) ★8 이상이 소모', self.catalog.reply('2611F2'))
        self.assertIsNone(next(r for r in self.catalog.items.values() if r['wiki_id']=='2611 F2')['game_api_id'])

    def test_saury_collection_is_inventory_not_sortie_or_consumption(self):
        for api, count in (('866',8),('867',16),('868',27)):
            row = self.catalog.items[api]
            self.assertEqual(row['category'], 'collection')
            self.assertIn(f'꽁치 {count}마리', self.catalog.detail(api))
            self.assertIn('소모하지 않음', self.catalog.detail(api))
        self.assertEqual((self.catalog.items['369']['requirements']['result'],
                          self.catalog.items['369']['requirements']['times']),('A',4))

    def test_updated_preparation_pool_does_not_keep_removed_ship_ids(self):
        row=self.catalog.items['386']
        pool=row['requirements']['comp'][0]['ship_id']
        self.assertIn(1003,pool)  # Shimane Maru
        self.assertIn(1055,pool)  # Bearn
        self.assertIn(144,pool)   # Yuudachi Kai Ni
        for removed in (637,931,941):self.assertNotIn(removed,pool)
