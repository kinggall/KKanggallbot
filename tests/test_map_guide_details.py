import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import map_guide_details as details


class MapGuideDetailTests(unittest.TestCase):
    def test_reviewed_6_4_enemy_pattern_probabilities_are_not_mixed(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'data/map_guide_reviewed.json').read_text(encoding='utf-8'))
        review=data['maps']['6-4'];boss=next(e for e in review['air'] if e['node']=='N')
        self.assertEqual((boss['superiority'],boss['supremacy']),(168,336))
        note=' '.join(review['notes'])
        for expected in ['25%','75%','우세 72','확보 144']:self.assertIn(expected,note)

    def test_priority_and_incompatible_missing_fields(self):
        primary={'node':'N','superiority':168}
        merged=details.merge_air(primary,{'superiority':72,'supremacy':144})
        self.assertEqual(merged['superiority'],168)
        self.assertNotIn('supremacy',merged)
        self.assertEqual(merged['conflicts'],['superiority'])
        self.assertEqual(details.merge_air(primary,{'superiority':168,'supremacy':336})['supremacy'],336)

    def test_sheet_multiline_cells_distinguish_nodes_and_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sheet.csv';stream=io.StringIO()
            writer=csv.writer(stream)
            writer.writerow(['3-5','G\nH(훗포)','16\n170','35\n381','69\n762','41이상(G)\n28이상(H)\n계수=4','fleet'])
            writer.writerow(['7-2-2','M(전초/최종/클후)','119\n160\n119','266\n359\n266','531\n717\n531','',''])
            writer.writerow(['5-6-기믹','R','','','제공60이상 추천','',''])
            writer.writerow(['5-3','Q67%\n/33%)','32\n63','71\n140','141\n279','',''])
            path.write_text(stream.getvalue(),encoding='utf-8')
            rows=details.reference_rows(path)
            h=next(e for e in rows if e.get('node')=='H')
            self.assertEqual(h['superiority'],381);self.assertEqual(h['supremacy'],762)
            stages=[e for e in rows if e['area']=='7-2']
            self.assertEqual([e['phase'] for e in stages],['공략 중','최종'])
            self.assertEqual(stages[1]['gauge'],'2')
            self.assertFalse(any(e['area']=='5-6' for e in rows))
            q=next(e for e in rows if e['area']=='5-3')
            self.assertEqual(q['node'],'Q');self.assertEqual(q['supremacy'],279)

    def test_only_nodes_on_route_and_same_gauge_are_used(self):
        review={'air':[{'node':'G','superiority':35},{'node':'H','superiority':381}]}
        variant={'summary':'경순1 구축5 【FGK】(K:보스)','phase':''}
        entries=details.air_entries('3-5',variant,review,[])
        self.assertEqual([e['node'] for e in entries],['G'])
        self.assertEqual(details.route_nodes('【ABC2DEG】'),{'A','B','C2','D','E','G'})
        review={'air':[{'node':'A','gauge':'1','superiority':275},{'node':'A','gauge':'3','superiority':503}]}
        variant={'summary':'【ABT】(T:보스)','phase':'3게이지'}
        self.assertEqual(details.air_entries('7-5',variant,review,[])[0]['superiority'],503)

    def test_boss_label_omitted_only_for_boss_and_parity_cutoff(self):
        entries=[{'node':'H','name':'홋포방','superiority':381,'supremacy':762,'parity':170}]
        self.assertEqual(details.air_lines(entries,{'K'}),['· H(홋포방) 제공: 균형 170 / 우세 381 / 확보 762'])
        entries=[{'node':'D','superiority':35,'supremacy':69,'parity':99},
                 {'node':'K','superiority':100,'supremacy':200,'parity':100}]
        lines=details.air_lines(entries,{'K'})
        self.assertEqual(lines,['· 제공: 균형 100 / 우세 100 / 확보 200'])

    def test_en_route_peak_and_boss_baseline_are_both_preserved(self):
        lines=details.air_lines([{'node':'C','superiority':252,'supremacy':504,'parity':113},
                                {'node':'O','superiority':176,'supremacy':351,'parity':79}],{'O'})
        self.assertEqual(len(lines),2)
        self.assertTrue(lines[0].startswith('· 제공:'))
        self.assertIn('C마스',lines[1]);self.assertNotIn('균형 79',' '.join(lines))

    def test_partial_air_raid_parity_is_not_lost(self):
        lines=details.air_lines([{'node':'E','parity':160},{'node':'P','superiority':236,'parity':106}],{'P'})
        self.assertEqual(len(lines),2)
        self.assertIn('E마스 제공: 균형 160',lines[1])

    def test_lower_shared_node_is_not_shown_as_extra_phase(self):
        lines=details.air_lines([{'node':'H','superiority':306},
                                {'node':'S','phase':'공략 중','superiority':392},
                                {'node':'S','phase':'격파 후','superiority':356}],{'S'})
        self.assertEqual(len(lines),2)
        self.assertFalse(any('H마스' in line for line in lines))

    def test_search_before_conditions_and_optional_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            variant={'summary':'항전1 구축5 【ABP】(P:보스)','phase':'',
                     'notes_jp':['編成とルート ※33式分岐点係数4で索敵値37以上必要 ルート条件 要 高速統一 (戦艦2隻編成) 陣形選択 単縦陣 コメント test']}
            lines=details.detail_lines('7-4',variant,Path(tmp))
            self.assertIn('색적 37 이상(33식·계수4)',' '.join(lines))
            self.assertIn('고속통일',' '.join(lines))
            variant['notes_jp']=['ルート条件 高速統一または重巡級0 陣形選択 単縦陣']
            self.assertNotIn('고속통일',' '.join(details.detail_lines('7-4',variant,Path(tmp))))

    def test_changed_source_does_not_keep_old_reviewed_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir();folder=root/'guide_cache/zekamashi_maps/1-1';folder.mkdir(parents=True)
            source=folder/'article.html';source.write_text('reviewed')
            review={'maps':{'1-1':{'source_html_sha256':hashlib.sha256(b'reviewed').hexdigest(),'notes':['reviewed Korean note']}}}
            (root/'data/map_guide_reviewed.json').write_text(json.dumps(review))
            variant={'summary':'구축4 【AC】(C:보스)','phase':'','notes_jp':[]}
            self.assertIn('reviewed Korean note',' '.join(details.detail_lines('1-1',variant,root)))
            source.write_text('changed')
            self.assertEqual(details.detail_lines('1-1',variant,root),['· 원문이 변경되어 상세 공략을 재검토 중입니다.'])

    def test_sheet_search_requires_reviewed_source_and_route(self):
        heading='specific fleet'
        review={'sheet_search':{heading:{'node':'G','evidence':'57이상','fleet_evidence':'색적 65이상','text':'색적 65 이상'}}}
        variant={'source_heading':heading,'summary':'【ABG】'}
        reference=[{'area':'5-6','search_text':'57이상','fleet_text':'항전2 (색적 65이상)'}]
        self.assertEqual(details.search_fallback('5-6',variant,review,reference),['색적 65 이상'])
        variant['summary']='【ABN】'
        self.assertEqual(details.search_fallback('5-6',variant,review,reference),[])
        variant['summary']='【ABG】';reference[0]['fleet_text']='different fleet'
        self.assertEqual(details.search_fallback('5-6',variant,review,reference),[])


if __name__=='__main__':unittest.main()
