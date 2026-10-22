import json
from pathlib import Path
import tempfile
import unittest

import guide_lookup
import map_guides


class GaugeGuideTests(unittest.TestCase):
    def record(self,root):
        folder=root/'guide_cache/zekamashi_maps/5-6';folder.mkdir(parents=True)
        routes=[]
        for number,gauge,node in [(1,1,'G'),(2,1,'G'),(3,2,'N'),(4,2,'N'),(5,3,'Z'),(6,3,'Z')]:
            name=f'{number}.jpg';(folder/name).write_bytes(b'image')
            variant={'phase':f'{gauge}게이지','source_heading':f'example {number}',
                     'summary':f'경순1 구축{number} 【AB{node}】({node}:보스)',
                     'images':[name],'airbase_images':[],'notes_jp':[]}
            routes.append({'number':number,'label':f'{gauge}게이지','variants':[variant]})
        record={'area':'5-6','status':'downloaded','routes':routes}
        (folder/'manifest.json').write_text(json.dumps(record),encoding='utf-8')
        return record

    def test_gauge_parser_does_not_change_collector_area_parser(self):
        for code in ['561','5-6-1','56-1','５６１']:
            self.assertEqual(map_guides.parse_map_query(code),('5-6',1))
        self.assertEqual(map_guides.parse_map_query('722'),('7-2',2))
        self.assertEqual(map_guides.parse_map_query('733'),('7-3',3)) # Recognized, then rejected as unavailable.
        for code in ['551','641','B561','By10','イ26']:
            self.assertIsNone(map_guides.parse_map_query(code))
        self.assertIsNone(map_guides.parse_area('561'))

    def test_three_levels_have_local_numbers_and_isolated_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.record(root)
            text,pictures=guide_lookup.build_preview('56',root=root)
            for gauge in [1,2,3]:
                self.assertIn(f'[{gauge}게이지]',text)
                self.assertIn(f'!공략 56{gauge} 루트1',text)
            self.assertEqual(text.count('루트1:'),3);self.assertEqual(text.count('루트2:'),3)
            self.assertNotIn('루트3:',text);self.assertEqual(len(pictures),6)
            text,pictures=guide_lookup.build_preview('562',root=root)
            self.assertIn('[2게이지]',text);self.assertNotIn('[1게이지]',text)
            self.assertEqual([p.name for p in pictures],['3.jpg','4.jpg'])
            self.assertNotIn('루트3',text)
            text,pictures=guide_lookup.build_preview('562 루트1',root=root)
            self.assertIn('경순1 구축3',text)
            self.assertEqual([p.name for p in pictures],['3.jpg'])
            self.assertEqual(guide_lookup.build_preview('562 루트2',root=root)[1][0].name,'4.jpg')
            self.assertEqual(guide_lookup.build_preview('563 루트1',root=root)[1][0].name,'5.jpg')
            self.assertEqual(guide_lookup.build_preview('5-6-2 루트1',root=root),guide_lookup.build_preview('562 루트1',root=root))
            self.assertIn('게이지를 먼저',guide_lookup.build_preview('56 루트1',root=root)[0])
            self.assertIn('등록된 게이지',guide_lookup.build_preview('564',root=root)[0])
            self.assertIn('해당 루트가 없습니다',guide_lookup.build_preview('562 루트3',root=root)[0])

    def test_single_route_inside_gauge_uses_detail_without_route_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);record=self.record(root)
            record['routes']=[record['routes'][0]]
            (root/'guide_cache/zekamashi_maps/5-6/manifest.json').write_text(json.dumps(record))
            text,pictures=guide_lookup.build_preview('561 상세',root=root)
            self.assertNotIn('루트1',text);self.assertEqual(len(pictures),1)
            self.assertIn('!공략 561 상세',guide_lookup.build_preview('561',root=root)[0])
            self.assertIn('!공략 561 상세',guide_lookup.build_preview('56',root=root)[0])
            self.assertEqual(guide_lookup.build_preview('561 루트1',root=root),('',[]))


if __name__=='__main__':unittest.main()
