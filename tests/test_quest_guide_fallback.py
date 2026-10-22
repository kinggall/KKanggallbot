import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import guide_lookup


class QuestGuideFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.quest={'wiki_id':'B77','name_ko':'수뢰전대 초계','name_jp':'試験任務',
                    'category':'sortie','requirements':{'category':'sortie',
                    'comp':[{'ship_id':123}],
                    'sortie':[{'map':['2-2','2-3'],'result':'S','times':1}]}}
        self.catalog=SimpleNamespace(by_code={'b77':'q'},items={'q':self.quest})
        self.patch=patch.object(guide_lookup.quests,'catalog',return_value=self.catalog)
        self.patch.start();self.addCleanup(self.patch.stop)
        for area in ['2-2','2-3','7-2','7-3','5-6']:self.add_map(area)

    def add_map(self,area):
        folder=self.root/'guide_cache/zekamashi_maps'/area;folder.mkdir(parents=True,exist_ok=True)
        (folder/'fleet.jpg').write_bytes(b'image')
        variants=[{'phase':'','summary':'경순1 구축5 【AB】(B:보스)',
                   'source_heading':'test','images':['fleet.jpg'],'airbase_images':[],'notes_jp':[]}]
        routes=[{'number':1,'label':'기본','variants':variants}]
        if area in {'7-2','7-3','5-6'}:
            routes=[]
            for stage in range(1,4 if area=='5-6' else 3):
                routes.append({'number':stage,'label':f'{stage}게이지',
                               'variants':[dict(variants[0],phase=f'{stage}게이지')]})
        (folder/'manifest.json').write_text(json.dumps({'area':area,'status':'downloaded','routes':routes}))

    def add_record(self,status='no_match_on_first_page'):
        folder=self.root/'guide_cache/zekamashi/B77';folder.mkdir(parents=True,exist_ok=True)
        (folder/'manifest.json').write_text(json.dumps({'code':'B77','name_jp':'試験任務',
                                                       'status':status,'schema_version':2}))

    def preview(self,query='B77'):
        with patch('requests.Session.request',side_effect=AssertionError('No network')):
            return guide_lookup.build_preview(query,root=self.root)

    def test_no_match_lists_quest_maps_and_warns_about_composition(self):
        self.add_record()
        text,images=self.preview()
        self.assertIn('등록된 임무 공략이 없습니다.',text)
        self.assertIn('해당해역: 2-2 / 2-3',text)
        self.assertIn('예: !공략 22',text)
        self.assertIn('임무 조건에 맞춰 편성을 조정하세요: !임무 B77',text)
        self.assertEqual(images,[])
        self.assertEqual(self.preview('b77'),(text,images))

    def test_missing_record_is_not_claimed_to_be_absent_from_website(self):
        text,_=self.preview()
        self.assertIn('아직 수집된 임무 공략',text)
        self.assertIn('해당해역: 2-2 / 2-3',text)

    def test_specific_gauges_are_preserved_without_guessing(self):
        self.add_record()
        self.quest['requirements']['sortie']=[{'map':['7-2M','7-3P','5-6Z']}]
        text,_=self.preview()
        self.assertIn('해당해역: 7-2-2 / 7-3-2 / 5-6-3',text)
        self.assertIn('예: !공략 722',text)
        text,_=self.preview('B77 563')
        self.assertIn('해당해역: 5-6-3',text)
        self.assertNotIn('7-2-2',text)

    def test_fixed_map_without_gauge_stays_unspecified(self):
        self.add_record();self.quest['requirements']['sortie']=[{'map':'7-2'}]
        text,_=self.preview();self.assertIn('예: !공략 72\n',text)
        self.assertNotIn('722',text)

    def test_no_fixed_map_does_not_invent_a_farming_area(self):
        self.add_record();self.quest['requirements']={'category':'simple','subcategory':'battle','times':1}
        text,_=self.preview()
        self.assertIn('고정된 대상 해역이 없는 임무',text)
        self.assertNotIn('!공략 11',text);self.assertNotIn('일반해역 공략을 참고',text)

    def test_unsupported_event_map_is_not_described_as_unrestricted(self):
        self.add_record();self.quest['requirements']['sortie']=[{'map':'E1'}]
        text,_=self.preview()
        self.assertIn('일반해역으로 연결할 수 없는',text)
        self.assertNotIn('고정된 대상 해역이 없는',text)

    def test_review_status_stays_visible_and_does_not_get_overwritten(self):
        self.add_record('review_required');text,_=self.preview()
        self.assertIn('확인이 필요한 자료',text)
        self.assertNotIn('등록된 임무 공략이 없습니다',text)
        self.assertIn('일반해역 공략을 참고',text)
        p=self.root/'guide_cache/zekamashi/B77/manifest.json'
        self.assertEqual(json.loads(p.read_text())['status'],'review_required')

    def test_invalid_or_unavailable_general_map_has_no_dead_example(self):
        self.add_record()
        text,_=self.preview('B77 722')
        self.assertIn('임무 대상 해역이 아닙니다',text);self.assertNotIn('예: !공략 722',text)
        p=self.root/'guide_cache/zekamashi_maps/2-3/manifest.json'
        data=json.loads(p.read_text());data['status']='review_required';p.write_text(json.dumps(data))
        text,_=self.preview()
        self.assertIn('해당해역: 2-2\n',text)
        self.assertIn('일반해역 공략 연결 확인 중: 2-3',text)

    def test_non_sortie_quest_is_not_linked_to_general_maps(self):
        self.add_record();self.quest['category']='factory'
        text,_=self.preview();self.assertNotIn('일반해역',text)


if __name__=='__main__':unittest.main()
