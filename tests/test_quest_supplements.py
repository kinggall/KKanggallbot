"""Missing translation records remain searchable without invented facts."""
import unittest
from pathlib import Path
from quests import QuestCatalog


class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = QuestCatalog(Path(__file__).resolve().parents[1])

    def test_all_fourteen_codes_and_compact_aliases(self):
        codes = ['2606 Am1', '5A04', 'Cs4', '2606 Cm1', 'SF', '2003LQ2',
                 '5A03', '2603 G2', '2212 B2', '2103 B5', '2107 LB1',
                 '2107 LB2', 'F132', 'F142']
        for code in codes:
            with self.subTest(code=code):
                reply = self.catalog.reply(code)
                self.assertTrue(reply.startswith(code + ':'))
                self.assertEqual(reply, self.catalog.reply(code.replace(' ', '').lower()))
                self.assertIn('보상 정보 미등록', reply)
                self.assertNotIn('보상 정보 없음', reply)

    def test_ship_search_and_existing_factory(self):
        found = self.catalog.search_keys('하나즈키')
        self.assertIn('199', found)
        self.assertIn('382', found)
        self.assertIn('1052', found)
        self.assertTrue(self.catalog.reply('Fy3').startswith('Fy3:'))

    def test_excludes_cooking_and_preserves_summer_variants(self):
        for n in range(1, 10):
            self.assertNotIn(f'su{n:02}', self.catalog.by_code)
        for code in ['Cs4', 'Cs5', 'Cs6']:
            self.assertTrue(self.catalog.reply(code).startswith(code + ':'))


if __name__ == '__main__':
    unittest.main()
