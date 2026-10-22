"""October wiki additions, graph, command parsing and offline guide previews."""
import io
import html
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import guide_lookup
import quests
from quest_updates import apply_updates
from scripts import collect_zekamashi
from scripts.import_new_quests import extract

ROOT = Path(__file__).resolve().parents[1]


class NewQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = quests.QuestCatalog(ROOT)
        cls.update = json.loads((ROOT/'data/quest_wiki_updates.json').read_text(encoding='utf-8'))

    def test_all_twelve_and_compact_codes(self):
        self.assertEqual(len(self.update['quests']), 12)
        for row in self.update['quests']:
            code = row['wiki_id']
            with self.subTest(code=code):
                text = self.catalog.reply(code.lower())
                self.assertTrue(text.startswith(code + ':'))
                self.assertEqual(text, self.catalog.reply(code.replace(' ', '').lower()))
                self.assertIn('[임무 내용]', text)
                self.assertIn('[보상]', text)
                self.assertNotIn('상세 조건 미등록', text)
                self.assertNotIn('등록 정보 없음', text)
                self.assertNotIn('종료)', text)
                self.assertIn(quests.UNVERIFIED, text)
                self.assertLess(len(text), 4000)

    def test_new_list_only_titles_and_numbers(self):
        text = self.catalog.new_quests_reply()
        self.assertIn('2026-10-14 점검 신규 임무 (12개)', text)
        for row in self.update['quests']:
            self.assertIn(f'· {row["wiki_id"]}: {row["name_ko"]}', text)
        self.assertIn('상세 내용: !임무 [번호]', text)
        self.assertNotIn('[보상]', text)
        self.assertNotIn('[임무 내용]', text)

    def test_new_list_changes_to_latest_maintenance(self):
        from copy import deepcopy
        future = deepcopy(self.update['quests'][0])
        future.update(release_date='2026-11-01', wiki_id='2611 B1', name_ko='다음 점검 임무')
        with patch.object(self.catalog, 'items', {**self.catalog.items, 'future':future}):
            text = self.catalog.new_quests_reply()
            self.assertIn('2026-11-01 점검 신규 임무 (1개)', text)
            self.assertIn('2611 B1', text)
            self.assertNotIn('2610 B1', text)
        with patch.object(self.catalog, 'items', {}):
            self.assertEqual(self.catalog.new_quests_reply(), '등록된 신규 임무가 없습니다.')

    def test_new_list_webhook_and_help(self):
        import bot
        self.assertIn('!신규임무', bot.COMMANDS['!도움말'])
        with patch.object(bot.requests, 'get', side_effect=AssertionError('No GET')), \
                patch.object(bot.requests, 'post') as post:
            response = bot.app.test_client().post('/webhook', json={
                'msg':'!신규임무','json':{'chat_id':'new-list-room'}})
            self.assertEqual(response.status_code, 200)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['json'], {
                'type':'text','room':'new-list-room','data':self.catalog.new_quests_reply()})

    def test_alias_search_includes_new_conditions(self):
        for query, expected in [('뽀이',{'2610 B1','2610 Bm2','2610 Cw1'}),
                                ('베이',{'2610 B2','2610 B4'}),
                                ('카시',{'2610 Bw1','2610 B3','2610 Bw2','2610 B4'})]:
            found = {self.catalog.items[k]['wiki_id'] for k in self.catalog.search_keys(query)}
            self.assertTrue(expected <= found)

    def test_sortie_maps_flagships_and_special_remodel(self):
        text = self.catalog.reply('2610B1')
        self.assertIn('중 3 이상(기함 포함)', text)
        self.assertIn('1-3/1-4/2-1 보스 S승 각 2회', text)
        text = self.catalog.reply('2610B3')
        self.assertIn('중 4 이상(기함 포함)', text)
        self.assertIn('1-1/1-3 보스 S승 각 4회', text)
        self.assertIn('진게이 개1', self.catalog.reply('2610Bm2'))
        self.assertIn('5-1/5-3/5-4/5-6-3 보스 S승 각 1회', self.catalog.reply('B218'))
        self.assertIn('아마기리 개2/개2정 중 1 + 사기리 개2', self.catalog.reply('B218'))

    def test_frequencies_consumables_and_reward_choices(self):
        for code in ('2610Bw1','2610Bw2','2610Cw1'):
            self.assertIn('(기간한정/주간)', self.catalog.reply(code))
        for code in ('2610Bm1','2610Bm2','2610Fm1'):
            self.assertIn('(기간한정/월간)', self.catalog.reply(code))
        self.assertIn('오늘 중 연습 A승 이상 5회', self.catalog.reply('2610Cw1'))
        self.assertIn('가구코인 x1031', self.catalog.reply('2610Fm1'))
        text = self.catalog.reply('2610F1')
        self.assertIn('호박 x2 / 3식 폭뢰투사기 x5 / 개발자재 x30', text)
        self.assertIn('장비 운용 슬롯 x15 / Type124 ASDIC ★3 / 해외함 최신기술 x3', text)
        self.assertIn('12.7cm 연장포 B형 개2 ★10', self.catalog.reply('B218'))

    def test_partial_prerequisites_reverse_without_guessing(self):
        b1 = self.catalog.items[self.catalog.by_code['2610b1']]
        self.assertEqual(b1['prereqs'], [])
        self.assertTrue(b1['prerequisite_incomplete'])
        self.assertIn('2610 Bw1 / 2610 Cw1 / 2610 Fm1', self.catalog.reply('2610B1'))
        self.assertIn('2610 Bw1 + 2610 B2', self.catalog.reply('2610Bm1'))
        self.assertIn('B218', self.catalog.reply('Bd5').split('[후속임무]')[1])
        for row in self.update['quests']:
            key = self.catalog.by_code[row['wiki_id'].replace(' ', '').lower()]
            for before in self.catalog.items[key]['prereqs']:
                self.assertIn(key, self.catalog.after[str(before)])

    def test_overlay_idempotent_and_no_fake_api_ids(self):
        data = self.catalog.data
        self.assertEqual(apply_updates(data, ROOT), data)
        self.assertEqual(self.catalog.by_code['2610b1'], '984')

    def test_eo_canonical_codes_have_no_conflicting_old_aliases(self):
        expected = {'2610b1':'984', '2610bw1':'985', '2610b2':'986',
                    '2610bm1':'987', '2610b3':'1038', '2610bw2':'1039',
                    '2610bm2':'1040', '2610b4':'1002', '2610cw1':'359',
                    '2610fm1':'1119', '2610f1':'1171'}
        for code, api_id in expected.items():
            self.assertEqual(self.catalog.by_code[code], api_id)
        for removed in ['2610b5', '2610b6', '2610b7', '2610b8', '2610c1', '2610f2']:
            self.assertNotIn(removed, self.catalog.by_code)

    def test_import_reproduces_reviewed_rows_and_rejects_changes(self):
        document = '<table>' + ''.join('<tr>' + ''.join(
            '<td>' + html.escape(cell) + '</td>' for cell in row['source_row']) + '</tr>'
            for row in self.update['quests']) + '</table>'
        self.assertEqual(extract(document)['quests'], self.update['quests'])
        with self.assertRaises(ValueError):
            extract(document.replace('各2回', '各3回', 1))
        with self.assertRaises(ValueError):
            extract('<table></table>')

    def test_actual_webhook_new_quest_replies_once(self):
        import bot
        for row in self.update['quests']:
            query = row['wiki_id'].replace(' ', '').lower()
            with self.subTest(query=query), patch.object(bot.requests, 'get', side_effect=AssertionError('No GET')), \
                    patch.object(bot.requests, 'post') as post:
                response = bot.app.test_client().post('/webhook', json={
                    'msg':'!임무 '+query,'json':{'chat_id':'new-quest-room'}})
                self.assertEqual(response.status_code, 200)
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['json']['data'], self.catalog.reply(query))

    def test_actual_guide_webhook_with_cached_fleet(self):
        import bot
        record = {'status':'downloaded','schema_version':2,
                  'code':'2610 B1', 'name_jp':self.update['quests'][0]['name_jp'],
                  'url':'https://zekamashi.net/kancolle-kouryaku/test/',
                  'images':[{'url':'https://zekamashi.net/wp-content/uploads/fleet.jpg','file':'fleet.jpg'}]}
        document = ('<h1>'+record['name_jp']+'</h1><div class="entry-content"><h2>編成例</h2><h3>1-3</h3>'
                    '<p><img src="https://zekamashi.net/wp-content/uploads/fleet.jpg"></p>'
                    '<p>軽空2駆逐4【CFJ】(C:通常 J:ボス)</p></div>')
        with patch.object(guide_lookup.quests, 'catalog', return_value=self.catalog), \
                patch.object(Path, 'read_text', lambda p,*a,**k:json.dumps(record) if p.name=='manifest.json' else document), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(Path, 'read_bytes', return_value=b'test-image'), \
                patch.object(bot.IMAGE_SEND_EXECUTOR, 'submit', side_effect=lambda fn:fn()), \
                patch.object(bot.requests, 'post') as post:
            response = bot.app.test_client().post('/webhook',json={
                'msg':'!공략 2610 B1 13','json':{'chat_id':'new-guide-room'}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args_list[0].kwargs['json']['type'], 'image_multiple')
            self.assertIn('1-3: 경항모2 구축4',post.call_args_list[1].kwargs['json']['data'])

    def test_new_collection_lists_all_without_network(self):
        output = io.StringIO()
        with patch('sys.argv', ['collect_zekamashi', '--new', '--dry-run']), \
                patch.object(collect_zekamashi, 'Fetcher', side_effect=AssertionError('No network')), \
                redirect_stdout(output):
            collect_zekamashi.main()
        self.assertIn('Targets: 12', output.getvalue())
        for row in self.update['quests']:
            self.assertIn(row['name_jp'], output.getvalue())

    def test_repair_scope_includes_factory_and_exercise(self):
        output=io.StringIO()
        with patch('sys.argv',['collector','--repair','--dry-run']), \
                patch.object(collect_zekamashi,'Fetcher',side_effect=AssertionError('No network')), \
                redirect_stdout(output):
            collect_zekamashi.main()
        self.assertIn('Targets: 286',output.getvalue())
        self.assertIn('2610 Fm1:',output.getvalue())
        self.assertIn('2610 Cw1:',output.getvalue())

    def test_guide_compact_and_spaced_codes_use_same_cache(self):
        for row in self.update['quests']:
            code = row['wiki_id']
            with self.subTest(code=code), patch.object(Path, 'read_text', side_effect=FileNotFoundError):
                # Catalog must be populated before mocking the cache reads.
                with patch.object(guide_lookup.quests, 'catalog', return_value=self.catalog):
                    spaced = guide_lookup.build_preview(code)
                    compact = guide_lookup.build_preview(code.replace(' ', ''))
                    self.assertEqual(spaced, compact)
                    self.assertTrue(spaced[0].startswith(code + ':'))
                    self.assertIn('아직 수집된 공략이 없습니다.', spaced[0])

    def test_new_sortie_guide_with_saved_image(self):
        record = {'status':'downloaded','schema_version':2,
                  'code':'2610 B1', 'name_jp':self.update['quests'][0]['name_jp'],
                  'url':'https://zekamashi.net/kancolle-kouryaku/test/',
                  'images':[{'url':'https://zekamashi.net/wp-content/uploads/fleet.jpg','file':'fleet.jpg'}]}
        html = ('<h1>'+record['name_jp']+'</h1><article><div class="entry-content"><h2>編成例</h2><h3>１－３</h3>'
                '<p><img src="https://zekamashi.net/wp-content/uploads/fleet.jpg"></p>'
                '<p>軽空2駆逐4【CFJ】(C:通常 F:通常 J:ボス)</p></div></article>')
        with patch.object(guide_lookup.quests, 'catalog', return_value=self.catalog), \
                patch.object(Path, 'read_text', lambda p,*a,**k: json.dumps(record) if p.name=='manifest.json' else html), \
                patch.object(Path, 'is_file', return_value=True):
            text, pictures = guide_lookup.build_preview('2610 B1 13')
            self.assertIn('1-3: 경항모2 구축4', text)
            self.assertEqual(len(pictures), 1)
            self.assertIn('2610_B1', str(pictures[0]))

    def test_non_sortie_collected_guide_is_text_only(self):
        record = {'status':'downloaded','schema_version':2,'text_only':True,
                  'code':'2610 Fm1','name_jp':next(r['name_jp'] for r in self.update['quests'] if r['wiki_id']=='2610 Fm1'),
                  'url':'https://zekamashi.net/kancolle-kouryaku/test/'}
        with patch.object(guide_lookup.quests, 'catalog', return_value=self.catalog), \
                patch.object(Path, 'read_text', lambda p,*a,**k: json.dumps(record) if p.name=='manifest.json' else '<h1>'+record['name_jp']+'</h1><div class="entry-content">本文</div>'):
            text, pictures = guide_lookup.build_preview('2610Fm1')
            self.assertEqual(pictures, [])
            self.assertIn('!임무 2610 Fm1', text)
            self.assertIn(record['url'], text)
