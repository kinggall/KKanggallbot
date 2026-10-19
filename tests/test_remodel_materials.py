import unittest
import csv
from pathlib import Path
from unittest.mock import patch

import remodel_materials as materials


class RemodelMaterialsTests(unittest.TestCase):
    def test_all_convert_routes_match_csv_and_render(self):
        with (Path(__file__).resolve().parents[1] / "ships.csv").open(encoding="cp932") as file:
            ships = {row["艦船ID"]: row for row in csv.DictReader(file)}
        routes = materials.convert_reference()
        self.assertEqual(len(routes), 53)
        for sid, route in routes.items():
            source = ships[sid]
            target = ships[str(route["target_id"])]
            self.assertEqual(source["改装後"], target["艦名"])
            self.assertEqual(source["改装Lv"], str(route["level"]))
            self.assertEqual(len(route["materials"]), 12)
            self.assertTrue(all(type(n) is int and n >= 0 for n in route["materials"]))
            text = materials.material_text(source, None)
            self.assertEqual(bool(text), any(route["materials"]))
        self.assertEqual(materials.material_text(ships['503'], None), ' · 재료 : 설계도 1/자재 10/건조재 20')
        self.assertEqual(materials.material_text(ships['508'], None), ' · 재료 : 자재 10/건조재 20')
        for sid in ('622', '623', '624'):
            self.assertEqual(materials.material_text(ships[sid], None), ' · 재료 : 자재 30/건조재 30')
        self.assertEqual(materials.material_text(ships['916'], None), ' · 재료 : 자재 50/건조재 50')

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
