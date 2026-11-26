import json
from pathlib import Path
import unittest
from scripts.collect_saury import parse_page

ROOT=Path(__file__).resolve().parents[1]


class SauryCollectionTests(unittest.TestCase):
    def test_source_fixture_matches_saved_rates_and_equipment(self):
        html=(ROOT/'tests/fixtures/saury_source.html').read_text(encoding='utf-8')
        data=parse_page(html)
        saved=json.loads((ROOT/'data/saury_source.json').read_text(encoding='utf-8'))
        for key in data:
            self.assertEqual(data[key],saved[key],key)
        self.assertEqual(data['rate_year'],2024)
        self.assertEqual(len(data['rows']),38)
        self.assertEqual(len(data['layout']),14)
        self.assertEqual(len(data['equipment_source']),20)
        self.assertEqual(data['rows'][0]['s'],'3.0')
        self.assertTrue(any(row['s'] is None for row in data['rows']))
        self.assertTrue(all('node' not in row for row in data['rows']))

    def test_changed_source_is_not_silently_accepted(self):
        html=(ROOT/'tests/fixtures/saury_source.html').read_text(encoding='utf-8')
        for broken in (html.replace('event-sanma2024/','unknown/'),
                       html.replace('S: 3.0%','S: 103.0%',1),
                       html.replace('class="map-icon fish"','class="other"',1),
                       html.replace('漁場ダメージ','',1)):
            with self.assertRaises(ValueError):parse_page(broken)
