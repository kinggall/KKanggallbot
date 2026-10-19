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
        self.data = json.loads((ROOT / 'data/kanlog_55_seed.json').read_text(encoding='utf-8'))

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
        for query in ('!드랍', '!드랍 7-5', '!드랍 5-5 B', '!드랍 5-5-P S extra'):
            self.assertEqual(drops.format_reply(query, self.data, str), drops.USAGE)
        self.assertIn('자료가 없습니다', drops.format_reply('!드랍 5-5-Z', self.data, str))

    def test_common_limited_included_and_unobserved_ranks_omitted(self):
        data = copy.deepcopy(self.data)
        data['rows'] = [dict(cell='19', ship_id=1, name='Test', rarity='common', limited=True,
                            ranks={'s': {'rate': 0.005, 'count': 1}, 'a': {'rate': 0, 'count': 0}})]
        self.assertEqual(drops.format_reply('!드랍 5-5', data, lambda i,n:n),
                         '5-5 Boss Drop\n· Test - S <0.01% (한정)')
        self.assertIn('기록이 없습니다', drops.format_reply('!드랍 5-5 A', data, lambda i,n:n))

    def test_parser_denominators_and_structural_failure(self):
        html = '''<button data-cell-no="19" data-cell-label="S">S(Boss)</button>
        集計: 2026/10/15 ～ 更新: 2026/10/19 23:00:27
        <tr class="js-drop-rate-row" data-row-key="19-1-0" data-map-lv="0"
          data-ship-id="1" data-ship-name="Test"
          data-m='["Test","common","type",0,0,0,0,0,0,0,1,0,0,1,0,0]'></tr>
        <script id="drop-rate-row-variant-data" type="application/json">
        {"19-1-0":{"s":{"r":10,"c":1}}}</script>
        <script id="drop-rate-rank-variant-total-data" type="application/json">
        {"0:s":{"19":10},"0:a":{"19":20}}</script>'''
        data = drops.parse_page(html)
        self.assertTrue(data['rows'][0]['limited'])
        self.assertEqual(data['period_start'], '2026/10/15')
        with self.assertRaises(ValueError):
            drops.parse_page(html.replace('"r":10', '"r":20'))
        with self.assertRaises((ValueError, KeyError)):
            drops.parse_page('<html>maintenance</html>')

    def test_schedule_and_persistent_retry_cache(self):
        now = datetime(2026, 10, 20, 1, 15, tzinfo=drops.JST).timestamp()
        self.assertEqual(datetime.fromtimestamp(drops.next_refresh(now), drops.JST).hour, 5)
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            with patch.object(requests, 'get', side_effect=requests.Timeout), self.assertLogs(drops.LOG, level='ERROR'):
                store.refresh_if_due(now)
            self.assertEqual(store.snapshot, self.data)
            restarted = drops.DropStore(directory)
            with patch.object(requests, 'get', side_effect=AssertionError('Must not immediately retry')):
                restarted.refresh_if_due(now + 60)
            self.assertEqual(restarted.due, now + 3600)

    def test_successful_refresh_is_saved_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = drops.DropStore(directory)
            fresh = dict(self.data, source_updated='2026/10/20 01:00:00')
            with patch.object(requests, 'get') as get, patch.object(drops, 'parse_page', return_value=fresh):
                get.return_value.text = 'mock page'
                store.refresh_if_due()
                get.assert_called_once()
            self.assertEqual(drops.DropStore(directory).snapshot, fresh)

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
