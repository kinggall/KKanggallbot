import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import guide_lookup
import quests

class GuideKeywordSearchTests(unittest.TestCase):
    def test_unique_title_and_spaces_resolve_to_same_quest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(guide_lookup.build_preview('아호작전',root),guide_lookup.build_preview('Bw1',root))
            self.assertEqual(guide_lookup.build_preview('아호 작전',root),guide_lookup.build_preview('Bw1',root))

    def test_ship_alias_unit_and_title_use_quest_search(self):
        catalog=quests.catalog()
        for query in ['뽀이','수상반격','6구','나구모']:
            found=[k for k in catalog.search_keys(query) if catalog.items[k].get('category')=='sortie']
            self.assertTrue(found,query)
            with tempfile.TemporaryDirectory() as temp:
                text,images=guide_lookup.build_preview(query,Path(temp))
                if len(found)==1:self.assertTrue(text.startswith(catalog.items[found[0]]['wiki_id']+':'))
                else:
                    for k in found[:30]:self.assertIn('('+catalog.items[k]['wiki_id']+')',text)
                    self.assertIn('번호 검색 예: !공략 ',text)
                self.assertEqual(images,[])

    def test_no_match_and_punctuation(self):
        text,images=guide_lookup.build_preview('존재하지않는임무키워드')
        self.assertIn('찾지 못했습니다',text)
        self.assertIn('키워드',text)
        self.assertEqual(images,[])
        self.assertEqual(guide_lookup.build_preview('!!!'),(guide_lookup.USAGE,[]))

    def test_keyword_with_map_and_map_command_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(guide_lookup.build_preview('아호작전 15',root),guide_lookup.build_preview('Bw1 15',root))
        with patch('map_guides.preview',return_value=('map',[])) as preview:
            self.assertEqual(guide_lookup.build_preview('55 중앙'),('map',[]))
            preview.assert_called_once()
