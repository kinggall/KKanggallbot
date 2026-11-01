"""Synthetic equipment fixtures, not claimed stats for unreleased equipment."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from equipment_updates import FIELDS, master_items, supplement_rows
from equipment_lookup import EquipmentCatalog
from scripts.update_equipment import build, MASTERS

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    rows = []
    for item_id in [*range(1, 501), 1000]:
        row = {field: 0 for field in FIELDS.values()}
        row.update(api_id=item_id, api_name=f'TEST equipment {item_id}',
                   api_type=[3, 5, 6, 6, 1], api_tyku=12, api_cost=5, api_distance=6)
        rows.append(row)
    return rows


class EquipmentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        shutil.copy2(ROOT / 'equipments.csv', self.root / 'equipments.csv')
        self.master = fixture()

    def fetch(self, url):
        if url in MASTERS:
            return deepcopy(self.master), 'fixture-master'
        return {'equipment': {f'TEST equipment {i}': f'테스트 장비 {i}' for i in range(1, 1001)}}, 'fixture-translation'

    def test_mapping_and_csv_precedence(self):
        document = build(self.root, self.fetch)
        self.assertIn(1000, [r['values']['装備ID'] for r in document['items']])
        self.assertNotIn(21, [r['values']['装備ID'] for r in document['items']])
        extra = next(r for r in document['items'] if r['values']['装備ID'] == 1000)
        self.assertEqual(extra['name'], '테스트 장비 1000')
        self.assertEqual(extra['values']['対空'], 12)
        self.assertEqual(extra['values']['配置コスト'], 5)
        baseline = EquipmentCatalog(ROOT)
        with patch('equipment_lookup.supplement_rows', return_value=[extra]):
            catalog = EquipmentCatalog(ROOT)
        self.assertEqual(catalog.search('테스트 장비 1000'), [1000])
        self.assertEqual(catalog.search('TEST equipment 1000'), [1000])
        self.assertIn('대공 +12', catalog.describe(1000))
        self.assertIn('배치코스트 5(보키 90) / 행동반경 6', catalog.describe(1000))
        self.assertEqual(catalog.describe(21), baseline.describe(21))

    def test_no_translation_falls_back_to_original(self):
        def fetch(url):
            document, digest = self.fetch(url)
            if url not in MASTERS:
                document['equipment'].pop('TEST equipment 1000')
            return document, digest
        self.assertEqual(build(self.root, fetch)['items'][-1]['name'], 'TEST equipment 1000')

    def test_duplicate_incomplete_and_non_numeric_master_rejected(self):
        with self.assertRaises(ValueError):
            master_items(self.master[:10])
        with self.assertRaises(ValueError):
            master_items(self.master + [self.master[0]])
        self.master[0]['api_tyku'] = '12'
        with self.assertRaises(ValueError):
            master_items(self.master)

    def test_conflicting_sources_rejected(self):
        def fetch(url):
            document, digest = self.fetch(url)
            if url == MASTERS[1]:
                document[-1]['api_tyku'] += 1
            return document, digest
        with self.assertRaises(ValueError):
            build(self.root, fetch)

    def test_published_addition_cannot_disappear_or_change_identity(self):
        document = build(self.root, self.fetch)
        path = self.root / 'data/equipment_updates.json'
        path.write_text(json.dumps(document), encoding='utf-8')
        original = path.read_bytes()
        self.master[-1]['api_name'] = 'Different identity'
        with self.assertRaises(ValueError):
            build(self.root, self.fetch)
        self.master.pop()
        with self.assertRaises(ValueError):
            build(self.root, self.fetch)
        self.assertEqual(path.read_bytes(), original)

    def test_runtime_snapshot_validation_and_idempotence(self):
        document = build(self.root, self.fetch)
        path = self.root / 'data/equipment_updates.json'
        path.write_text(json.dumps(document), encoding='utf-8')
        self.assertEqual(build(self.root, self.fetch), document)
        self.assertTrue(supplement_rows(self.root))
        document['items'].append(document['items'][0])
        path.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(ValueError):
            supplement_rows(self.root)


if __name__ == '__main__':
    unittest.main()
