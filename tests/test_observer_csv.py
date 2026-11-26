import hashlib
import json
from pathlib import Path
import unittest
from scripts.import_observer_csv import normalize_ships, read_csv

ROOT = Path(__file__).resolve().parents[1]


class ObserverCSVTests(unittest.TestCase):
    def test_numeric_links_items_and_unknown_sentinels(self):
        rows=[{'艦船ID':'1','艦名':'テスト','改装前':'0','改装後':'2','初期装備1':'7','初期装備2':'-1',
               '対潜初期最小':'10','対潜最大':'9999','回避初期最小':'12','回避最大':'30',
               '索敵初期最小':'1','索敵最大':'9','建造時間':'75'},
              {'艦船ID':'2','艦名':'テスト改','改装前':'1','改装後':'0','対潜初期最小':'10','対潜最大':'20',
               '回避初期最小':'12','回避最大':'30','索敵初期最小':'1','索敵最大':'9'}]
        result=normalize_ships(rows,[{'装備ID':'7','装備名':'テスト装備'}],[{'艦船ID':'1','初期装備2':'???'}])
        self.assertEqual(result[0]['改装後'],'テスト改')
        self.assertEqual(result[0]['初期装備1'],'テスト装備')
        self.assertEqual(result[0]['初期装備2'],'???')
        self.assertEqual(result[0]['対潜最大'],'???')
        self.assertEqual(result[0]['対潜初期'],'10')
        self.assertEqual(result[0]['建造時間'],'01:15:00')
        self.assertEqual(result[1]['改装前'],'テスト')
        self.assertEqual(rows[0]['改装後'],'2')

    def test_imported_files_match_provenance_and_preserve_counts(self):
        manifest=json.loads((ROOT/'data/observer_source/manifest.json').read_text())
        for path,key in [('ships.csv','ships_runtime_sha256'),('equipments.csv','equipment_sha256'),
                         ('data/observer_source/ships.csv','ships_source_sha256')]:
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),manifest[key])
        _,ships=read_csv(ROOT/'ships.csv')
        self.assertEqual(sum(0<int(r['艦船ID'])<1500 for r in ships),870)
        by_id={r['艦船ID']:r for r in ships}
        self.assertEqual(by_id['951']['初期装備1'],'???')
        self.assertEqual(by_id['902']['対潜最大'],'81')
        self.assertEqual(by_id['1060']['対潜最大'],'???')

    def test_november_reconnaissance_forms_and_existing_stat_changes(self):
        _, ships=read_csv(ROOT/'ships.csv')
        by_name={r['艦名']:r for r in ships}
        for name,parent in (('由良改二偵','由良改二'),('川内改二偵','川内改二'),
                            ('高波改二偵','高波改二'),('青葉改偵','青葉改')):
            self.assertEqual(by_name[name]['改装前'],parent)
            self.assertEqual(by_name[parent]['改装後'],name)
        self.assertEqual(by_name['磯波改二']['火力最大'],'59')
        self.assertEqual(by_name['浦波改二']['雷装最大'],'87')
        self.assertEqual(by_name['秋雲改二']['対空最大'],'67')
