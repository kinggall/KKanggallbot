import unittest
from unittest.mock import patch

import remodel_materials as materials


class RemodelMaterialsTests(unittest.TestCase):
    def test_forward_target_cost_and_accent_matching(self):
        source = {"艦名": "Bearn改", "改装後": "Bearn amelioration", "改装Lv": "75", "改装設計図": "1枚"}
        text = materials.material_text(source, {})
        self.assertIn("자재 60", text)
        self.assertIn("건조재 40", text)
        self.assertNotIn("미확인", text)

    def test_convert_does_not_reuse_initial_blueprints(self):
        source = {"艦名": "大和改二重", "改装後": "大和改二", "改装Lv": "88"}
        self.assertEqual(materials.material_text(source, {}), "")
        self.assertEqual(materials.material_text(source, None), "")

    def test_missing_reference_retains_only_known_csv_costs(self):
        source = {"艦名": "test", "改装後": "unknown", "改装設計図": "2枚"}
        self.assertEqual(materials.material_text(source, {}), " · 재료 : 설계도 2")
        with patch.object(materials, "reference", side_effect=OSError):
            self.assertIn("설계도 2", materials.material_text(source, {}))
