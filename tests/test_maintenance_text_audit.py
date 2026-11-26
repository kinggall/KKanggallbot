import json
from pathlib import Path
import unittest

from scripts.audit_maintenance_text import compare_body
from scripts.collect_maintenance import source_hash


class TextAuditTests(unittest.TestCase):
    def setUp(self):
        self.post={'number':8,'id':'108','date':'2026-11-24',
                   'url':'https://x.com/KanColle_STAFF/status/108',
                   'text':'08▼本文……です。\n#艦これ\n…\nhttps://t.co/quote'}
        self.response={'id_str':'108','user':{'screen_name':'KanColle_STAFF'},
                       'created_at':'2026-11-24T10:00:00Z','text':'08▼本文……です。 #艦これ'}

    def test_embed_tail_is_not_a_missing_sentence_and_dialogue_is_preserved(self):
        result=compare_body(self.post,self.response)
        self.assertTrue(result['body_matches'])
        self.assertIn('……',result['syndication_text'])

    def test_actual_missing_content_is_not_silently_dismissed(self):
        self.response['text']+='\n追加の条件です。'
        self.assertFalse(compare_body(self.post,self.response)['body_matches'])

    def test_identity_date_and_truncated_responses_are_rejected(self):
        for changes in ({'id_str':'109'},{'user':{'screen_name':'other'}},
                        {'created_at':'2026-11-11T10:00:00Z'},
                        {'text':'09▼wrong'}, {'truncated':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                compare_body(self.post,self.response | changes)

    def test_all_eleven_real_audits_match_current_source_and_digest_hash(self):
        root=Path(__file__).resolve().parents[1]
        audit=json.loads((root/'data/maintenance_text_audit_20261124.json').read_text())
        self.assertEqual([r['number'] for r in audit['posts']],[1,6,7,8,9,10,11,19,20,21,23])
        source=json.loads((root/'data/maintenance_posts.json').read_text())
        current={r['number']:r for r in source['posts']}
        for row in audit['posts']:
            self.assertTrue(row['body_matches'])
            self.assertEqual(current[row['number']]['text'],row['syndication_text'])
        self.assertEqual(source['possibly_truncated_numbers'],[])
        self.assertEqual(source_hash(source['posts']),source['source_sha256'])
        digest=json.loads((root/'data/maintenance_summary.json').read_text())
        self.assertEqual(digest['source_sha256'],source['source_sha256'])
