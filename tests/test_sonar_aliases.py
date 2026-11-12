from pathlib import Path
import unittest

from equipment_lookup import EquipmentCatalog
from development import DevelopmentCatalog
from improvement import ImprovementCatalog

ROOT = Path(__file__).resolve().parents[1]


class SonarAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.equipment = EquipmentCatalog(ROOT)
        cls.development = DevelopmentCatalog(ROOT)
        cls.improvement = ImprovementCatalog(ROOT)

    def test_sonar_aliases_work_for_equipment_development_and_improvement(self):
        cases = {
            '三式水中探信儀': ('3식 소나','3식소나','삼식소나','3식 소너'),
            '九三式水中聴音機': ('93식 소나','93식소나','구삼식소나','93식 소너'),
            '四式水中聴音機': ('4식 소나','4식소나','사식소나','4식 소너'),
            '零式水中聴音機': ('0식 소나','0식소나','영식소나','0식 소너','0식 수중청음기'),
        }
        for original, aliases in cases.items():
            expected = self.equipment.search(original)
            self.assertEqual(len(expected),1)
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertEqual(self.equipment.search(alias),expected)
                    self.assertEqual(self.development.reply(alias,self.equipment),self.development.reply(original,self.equipment))
                    self.assertEqual(self.improvement.reply(alias,{}),self.improvement.reply(original,{}))
