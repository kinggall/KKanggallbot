import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance
from scripts.collect_maintenance import ACCOUNT, PROFILE, collect, collect_timeline, extract_posts, source_hash


def post(number, post_id, account=ACCOUNT):
    return {'rest_id': str(post_id), 'core': {'user_results': {'result': {'core': {'screen_name': account}}}},
            'details': {'full_text': f'{number:02d}▼公示', 'created_at_ms': 1794390886000}}


def page(*posts):
    document = json.dumps({'posts': posts}, ensure_ascii=False)
    return '<script>callback({data:' + json.dumps(document, ensure_ascii=False) + '})</script>'


class TimelinePage:
    def __init__(self, batches, text=''):
        self.batches, self.text, self.position = batches, text, 0
        self.mouse = self

    def goto(self, *_args, **_kwargs):
        pass

    def wait_for_timeout(self, _milliseconds):
        pass

    def locator(self, _selector):
        return self

    def evaluate_all(self, _expression):
        return self.batches[min(self.position, len(self.batches) - 1)]

    def inner_text(self):
        return self.text

    def wheel(self, *_args):
        self.position += 1


class MaintenanceTests(unittest.TestCase):
    def test_only_official_numbered_posts_are_extracted_without_running_javascript(self):
        html = page(post(1, 101), post(2, 102, 'somebody_else'))
        self.assertEqual([p['number'] for p in extract_posts(html)], [1])
        self.assertEqual(extract_posts(html)[0]['url'], PROFILE + '/status/101')
        self.assertEqual(extract_posts('<html>Sign in</html>'), [])

    def test_walks_back_to_01_instead_of_stopping_at_profile(self):
        pages = {PROFILE: page(post(5, 105)), PROFILE + '/status/105': page(post(4, 104), post(3, 103)),
                 PROFILE + '/status/103': page(post(2, 102), post(1, 101))}
        result = collect(pages.__getitem__)
        self.assertEqual([p['number'] for p in result['posts']], list(range(1, 6)))
        self.assertEqual(result['missing_numbers'], [])

    def test_missing_number_is_recorded_without_inventing_its_contents(self):
        pages = {PROFILE: page(post(4, 104)), PROFILE + '/status/104': page(post(2, 102), post(1, 101)),
                 PROFILE + '/status/102': page(post(2, 102), post(1, 101))}
        result = collect(pages.__getitem__)
        self.assertEqual(result['missing_numbers'], [3])
        self.assertEqual(len(result['posts']), 3)

    def test_conflicting_numbers_fail(self):
        pages = {PROFILE: page(post(3, 103)), PROFILE + '/status/103': page(post(3, 999), post(1, 101))}
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            collect(pages.__getitem__)

    def test_additional_official_link_fills_quote_chain_gap(self):
        url = PROFILE + '/status/103'
        pages = {PROFILE: page(post(4, 104), post(2, 102), post(1, 101)), url: page(post(3, 103))}
        result = collect(pages.__getitem__, extra_urls=[url])
        self.assertEqual(result['missing_numbers'], [])
        self.assertEqual(result['additional_source_urls'], [url])
        self.assertEqual([p['number'] for p in result['posts']], [1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, 'official'):
            collect(pages.__getitem__, extra_urls=['https://example.com/status/103'])

    def test_timeline_collects_unquoted_post_discovered_only_after_scrolling(self):
        missing_url = PROFILE + '/status/103'
        pages = {PROFILE: page(post(4, 104), post(2, 102), post(1, 101)), missing_url: page(post(3, 103))}
        browser = TimelinePage([[], [missing_url, 'https://example.com/status/999']])
        fetched = []

        def fetch(url):
            fetched.append(url)
            return pages[url]

        result = collect_timeline(fetch, browser)
        self.assertEqual(result['collection_method'], 'timeline_scroll')
        self.assertEqual([p['number'] for p in result['posts']], [1, 2, 3, 4])
        self.assertEqual(fetched, [PROFILE, missing_url])
        self.assertEqual(browser.position, 1)

    def test_login_wall_never_counts_as_complete_timeline(self):
        browser = TimelinePage([[]], text='See full profile. Continue to X. Log in or sign up for X')
        with self.assertRaisesRegex(ValueError, r'login required; missing \[1, 2\]'):
            collect_timeline(lambda _: page(post(3, 103)), browser)

    def test_stalled_timeline_without_login_also_fails(self):
        with self.assertRaisesRegex(ValueError, 'timeline stopped loading'):
            collect_timeline(lambda _: page(post(3, 103)), TimelinePage([[]]))

    def test_requested_date_can_be_below_the_initial_screen(self):
        newer = post(1, 201)
        newer['details']['created_at_ms'] += 86400000
        target_url = PROFILE + '/status/101'
        pages = {PROFILE: page(newer), target_url: page(post(1, 101))}
        result = collect_timeline(pages.__getitem__, TimelinePage([[], [target_url]]), date='2026-11-11')
        self.assertEqual([p['id'] for p in result['posts']], ['101'])

    def test_older_dates_are_not_mixed_into_current_maintenance(self):
        older = post(1, 101)
        older['details']['created_at_ms'] -= 86400000
        with self.assertRaisesRegex(ValueError, 'No official maintenance'):
            collect(lambda _: page(older), date='2026-11-11')

    def test_new_source_does_not_reuse_stale_reviewed_summary(self):
        root = Path(__file__).resolve().parents[1]
        source = json.loads((root / 'data/maintenance_posts.json').read_text())
        summary = json.loads((root / 'data/maintenance_summary.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / 'data').mkdir()
            (temp / 'data/maintenance_summary.json').write_text(json.dumps(summary))
            source = copy.deepcopy(source)
            source['posts'][0]['text'] += ' changed'
            source['source_sha256'] = source_hash(source['posts'])
            (temp / 'data/maintenance_posts.json').write_text(json.dumps(source))
            self.assertIn('검토 중', maintenance.reply(temp))
            self.assertNotIn('■ 시즌 전환', maintenance.reply(temp))

    def test_webhook_serves_summary_for_full_and_initial_command(self):
        import bot
        with patch.object(bot.requests, 'post') as send:
            for command in ('!멘테', '!ㅁㅌ'):
                response = bot.app.test_client().post('/webhook', json={'msg': command, 'json': {'chat_id': 'room'}})
                self.assertEqual(response.status_code, 200)
                text = send.call_args.kwargs['json']['data']
                self.assertIn('[멘테 · 2026-11-11]', text)
                self.assertNotIn('원문 미확보', text)
                self.assertIn('55cm 삼연장어뢰', text)
                self.assertNotIn('gall.dcinside', text)


if __name__ == '__main__':
    unittest.main()
