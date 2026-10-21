import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import requests
import kanlog_drops as drops

ROOT = Path(__file__).resolve().parents[1]


class KanlogTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'data/kanlog_maps_seed.json').read_text(encoding='utf-8'))['maps']['5-5']

    def test_real_boss_and_rank_selection_without_network(self):
        for query, expected in [
            ('!드랍 5-5', '· 比叡 - S 12.84% / A 6.84%'),
            ('!드랍 5-5 S', '· 比叡 - S 12.84%'),
            ('!드랍 5-5 A', '· 比叡 - A 6.84%'),
        ]:
            with patch.object(requests, 'get', side_effect=AssertionError('Commands must be offline')):
                text = drops.format_reply(query, self.data, lambda i, n: n)
            self.assertIn(expected, text)
            self.assertNotIn('\n\n', text)
            self.assertNotIn('No Drop', text)
            self.assertNotIn('青葉', text)  # Common, non-limited.
            if query.endswith(' S'):
                self.assertNotIn(' / A ', text)
            if query.endswith(' A'):
                self.assertNotIn(' S ', text)
        text = drops.format_reply('!드랍 5-5', self.data, lambda i, n: n)
        self.assertIn('· Atlanta - S 1.06% / A 1.21% (한정)', text)

    def test_specific_node_rank_case_and_invalid_queries(self):
        text = drops.format_reply('!드랍 5-5-p s', self.data, lambda i, n: n)
        self.assertTrue(text.startswith('5-5-P Drop (S승)\n'))
        self.assertNotIn('Boss', text)
        self.assertNotIn(' / A ', text)
        for query in ('!드랍', '!드랍 8-5', '!드랍 5-5 B', '!드랍 5-5-P S extra'):
            self.assertEqual(drops.format_reply(query, self.data, str), drops.USAGE)
        self.assertIn('자료가 없습니다', drops.format_reply('!드랍 5-5-Z', self.data, str))

    def test_common_limited_included_and_unobserved_ranks_omitted(self):
        data = copy.deepcopy(self.data)
        data['rows'] = [dict(cell='19', ship_id=1, name='Test', rarity='common', limited=True,
                            ranks={'s': {'rate': 0.005, 'count': 1}, 'a': {'rate': 0, 'count': 0}})]
        self.assertEqual(drops.format_reply('!드랍 5-5', data, lambda i,n:n),
                         '5-5 Boss Drop (S/A)\n· Test - S <0.01% (한정)')
        self.assertIn('기록이 없습니다', drops.format_reply('!드랍 5-5 A', data, lambda i,n:n))

    def test_short_map_queries_and_ship_name_separation(self):
        for query in ('55p', '55P', '5-5-P', '5-5p', '55-P'):
            self.assertEqual(drops.parse_map_query(query), ('5-5', 'P', None))
            self.assertEqual(drops.format_reply('!드랍 '+query, self.data, lambda i,n:n),
                             drops.format_reply('!드랍 5-5-P', self.data, lambda i,n:n))
        self.assertTrue(drops.format_reply('!드랍 55', self.data, lambda i,n:n).startswith('5-5 Boss Drop (S/A)\n'))
        self.assertTrue(drops.format_reply('!드랍 55p s', self.data, lambda i,n:n).startswith('5-5-P Drop (S승)\n'))
        for name in ('이26', '이-26', '伊26', 'U-511', '로500', '뽀이', '2411', '55팬티'):
            self.assertIsNone(drops.parse_map_query(name), name)

    def test_ship_query_returns_top_locations(self):
        data = copy.deepcopy(self.data)
        data['cells']['19']['boss'] = True
        text = drops.format_reply(
            '!드랍 아사시오', data, lambda i, n: n,
            lambda keyword: {1},
        )
        self.assertTrue(text.startswith('아사시오 Drop Table\n'))
        self.assertRegex(text, r'· 5-5 [A-Z] - S ')
        self.assertNotIn('S/A', text)
        self.assertLessEqual(len(text.splitlines()), 26)

    def test_unknown_ship_query_is_distinct_from_map_usage(self):
        text = drops.format_reply(
            '!드랍 존재하지않는함선', self.data, str,
            lambda keyword: set(),
        )
        self.assertEqual(text, drops.USAGE)

    def test_parser_denominators_and_structural_failure(self):
        html = '''<button data-cell-no="19" data-cell-label="S">S(Boss)</button>
        集計: 2026/10/15 ～ 更新: 2026/10/19 23:00:27
        <tr class="js-drop-rate-row" data-row-key="19-1-0" data-map-lv="0"
          data-ship-id="1" data-ship-name="Test"
          data-m='["Test","common","type",0,0,0,0,0,0,0,1,0,0,1,0,0]'></tr>
        <script id="drop-rate-row-variant-data" type="application/json">
        {"19-1-0":{"s":{"r":100,"c":1}}}</script>
        <script id="drop-rate-rank-variant-total-data" type="application/json">
        {"0:s":{"19":1},"0:a":{"19":0}}</script>'''
        data = drops.parse_page(html)
        self.assertTrue(data['rows'][0]['limited'])
        self.assertEqual(data['period_start'], '2026/10/15')
        with self.assertRaises(ValueError):
            drops.parse_page(html.replace('"r":100', '"r":20'))
        with self.assertRaises((ValueError, KeyError)):
            drops.parse_page('<html>maintenance</html>')

    def test_schedule_and_persistent_retry_cache(self):
        now = datetime(2026, 10, 20, 1, 15, tzinfo=drops.JST).timestamp()
        self.assertEqual(datetime.fromtimestamp(drops.next_refresh(now), drops.JST).hour, 3)
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            store.due = 0
            with patch.object(requests, 'get', side_effect=requests.Timeout), patch.object(drops.time, 'time', return_value=now), self.assertLogs(drops.LOG, level='ERROR'):
                store.refresh_if_due(now)
            self.assertEqual(store.snapshot['maps']['5-5'], self.data)
            restarted = drops.DropStore(directory)
            with patch.object(requests, 'get', side_effect=AssertionError('Must not immediately retry')):
                restarted.refresh_if_due(now + 60)
            self.assertGreater(restarted.due, now + 60)

    def test_successful_refresh_is_saved_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            store.due = 0
            fresh = dict(store.snapshot['maps']['1-1'], source_updated='2099/10/20 01:00:00')
            with patch.object(requests, 'get') as get, patch.object(drops, 'parse_page', return_value=fresh):
                get.return_value.text = 'mock page'
                store.refresh_if_due()
                get.assert_called_once()
            self.assertEqual(drops.DropStore(directory).snapshot['maps']['1-1'], fresh)

    def test_full_seed_and_all_map_node_rank_commands(self):
        bundle = json.loads((ROOT / 'data/kanlog_maps_seed.json').read_text(encoding='utf-8'))
        self.assertEqual(set(bundle['maps']), set(drops.MAPS))
        for name, snapshot in bundle['maps'].items():
            labels = [None] + [c['label'] for c in snapshot['cells'].values()]
            for label in labels:
                for rank in ('', ' S', ' A'):
                    query = name.replace('-', '') + (label or '') + rank
                    text = drops.format_reply('!드랍 ' + query, bundle, lambda i,n:n)
                    self.assertNotEqual(text, drops.USAGE, query)
                    self.assertNotIn('자료를 준비 중', text)
                    self.assertNotIn('\n\n', text)
                    self.assertLess(len(text), 4096)
            for row in snapshot['rows']:
                for rank, value in row['ranks'].items():
                    total = snapshot['totals']['0:' + rank][row['cell']]
                    self.assertAlmostEqual(value['rate'], value['count'] * 100 / total, delta=0.00011)

    def test_multi_boss_stages_and_no_boss(self):
        bundle = json.loads((ROOT / 'data/kanlog_maps_seed.json').read_text(encoding='utf-8'))
        for name, labels in drops.BOSS_STAGES.items():
            final = drops.format_reply('!드랍 ' + name, bundle, lambda i,n:n).splitlines()[1:]
            explicit = drops.format_reply('!드랍 ' + name + '-' + labels[-1], bundle, lambda i,n:n).splitlines()[1:]
            self.assertEqual(final, explicit)
            for number, label in enumerate(labels, 1):
                stage = drops.format_reply(f'!드랍 {name}-{number}', bundle, lambda i,n:n)
                node = drops.format_reply(f'!드랍 {name}-{label}', bundle, lambda i,n:n)
                self.assertEqual(stage.splitlines()[1:], node.splitlines()[1:])
        self.assertEqual(drops.format_reply('!드랍 16', bundle, lambda i,n:n), '보스방이 존재하지 않습니다.')
        self.assertTrue(drops.format_reply('!드랍 16b', bundle, lambda i,n:n).startswith('1-6-B Drop (S/A)\n'))
        self.assertTrue(drops.format_reply('!드랍 56q2', bundle, lambda i,n:n).startswith('5-6-Q2 Drop (S/A)\n'))

    def test_refresh_spacing_resume_and_cycle_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            store.due = 0
            fresh = store.snapshot['maps']['1-1']
            with patch.object(requests, 'get') as get, patch.object(drops, 'parse_page', return_value=fresh), patch.object(drops.time, 'time', return_value=1000):
                get.return_value.text = 'mock'
                store.refresh_if_due(1000)
                self.assertEqual(store.due, 1010)
                self.assertEqual(len(store.remaining), 37)
                get.assert_called_once()
                restarted = drops.DropStore(directory)
                self.assertEqual(restarted.remaining, store.remaining)
                restarted.refresh_if_due(1009)
                get.assert_called_once()
            restarted.remaining = ['1-1']
            restarted.due = 0
            with patch.object(requests, 'get'), patch.object(drops, 'parse_page', return_value=fresh):
                restarted.refresh_if_due()
            self.assertEqual(restarted.remaining, [])
            self.assertGreater(restarted.due, 0)

    def test_webhook_uses_original_room_and_no_get(self):
        import bot
        with patch.object(requests, 'get', side_effect=AssertionError('No network during command')), patch.object(requests, 'post') as post:
            post.return_value.status_code = 200
            response = bot.app.test_client().post('/webhook', json={'msg':'!드랍 5-5 S', 'json':{'chat_id':'123'}})
            self.assertEqual(response.status_code, 200)
            body = post.call_args.kwargs['json']
            self.assertEqual(body['room'], '123')
            self.assertIn('· 히에이 - S 12.84%', body['data'])
            self.assertNotIn(' / A ', body['data'])

    def test_rare_index_refresh_uses_one_request_and_persists(self):
        rare = json.loads((ROOT / 'data/kanlog_rare_seed.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            store.remaining = [drops.RARE_TASK]
            store.due = 0
            with (patch.object(requests, 'get') as get,
                  patch.object(drops, 'parse_rare_page', return_value=rare)):
                get.return_value.text = 'mock'
                store.refresh_if_due()
            get.assert_called_once()
            self.assertEqual(get.call_args.args[0], drops.RARE_URL)
            self.assertEqual(store.remaining, [])
            restarted = drops.DropStore(directory)
            self.assertEqual(restarted.snapshot['rare'], rare)

    def test_rare_index_seed_has_only_badged_ships(self):
        rare = json.loads((ROOT / 'data/kanlog_rare_seed.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rare['groups']), 8)
        self.assertEqual(sum(map(len, rare['groups'].values())), 68)
        self.assertEqual(rare['groups']['경순'], ['朝日', '能代', '鹿島', 'Atlanta'])
        self.assertNotIn('Phoenix', rare['groups']['경순'])

    def test_limited_drop_groups_use_rare_page_badges_only(self):
        import bot
        bundle = {'rare': json.loads((ROOT / 'data/kanlog_rare_seed.json').read_text(encoding='utf-8'))}
        with patch.object(requests, 'get', side_effect=AssertionError('No GET for commands')):
            reply = drops.format_limited_reply(bundle, bot.kanlog_ship_name)
        self.assertEqual([line for line in reply.splitlines() if line.startswith('[')],
                         [f'[{group}]' for group in drops.LIMITED_GROUPS])
        self.assertIn('[경순]\n아사히 / 노시로 / 카시마 / 애틀랜타', reply)
        self.assertIn('\n\n[경순]\n', reply)
        self.assertNotIn('피닉스', reply)
        self.assertLess(len(reply), 4000)

    def test_ended_24_drops_excluded_from_both_lookup_directions(self):
        bundle = json.loads((ROOT / 'data/kanlog_maps_seed.json').read_text(encoding='utf-8'))
        reply = drops.format_reply('!드랍 2-4', bundle, lambda i, n: n)
        self.assertNotIn('Phoenix', reply)
        self.assertNotIn('Heywood', reply)
        for ship_id in (952, 941):
            reverse = drops.format_reply('!드랍 test', bundle, lambda i, n: n, lambda _: {ship_id})
            self.assertNotIn('2-4 Boss', reverse)

    def test_limited_drop_webhook_preserves_room_and_help(self):
        import bot
        self.assertIn('!한정드랍', bot.COMMANDS['!도움말'])
        self.assertNotIn('!기간한정', bot.COMMANDS['!도움말'])
        with (patch.object(requests, 'get', side_effect=AssertionError('No GET for commands')),
              patch.object(requests, 'post') as post):
            post.return_value.status_code = 200
            response = bot.app.test_client().post('/webhook', json={
                'msg': '!한정드랍', 'json': {'chat_id': '123'},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_args.kwargs['json']['room'], '123')
        self.assertIn('[구축]\n', post.call_args.kwargs['json']['data'])
