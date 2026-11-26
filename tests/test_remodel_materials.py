import unittest
import csv
from pathlib import Path
from unittest.mock import patch

import remodel_materials as materials


class RemodelMaterialsTests(unittest.TestCase):
    def test_new_reconnaissance_costs_include_equipment_counts_and_minimum_stars(self):
        import bot
        cases = ((488,750,55,22,3,'21호 대공전탐',1),
                 (158,751,55,22,3,'22호 대수상전탐',1),
                 (649,752,36,18,2,'22호 대수상전탐',1),
                 (264,753,120,36,4,'21호 대공전탐',2))
        for sid,target,dev,build,arsenal,radar,lookouts in cases:
            with self.subTest(sid=sid):
                source=bot.SHIP_BY_GAME_ID[sid]
                text=materials.material_text(source,bot.SHIP_BY_GAME_ID[target])
                self.assertIn(f'자재 {dev}/건조재 {build}/공창자원 {arsenal}',text)
                self.assertIn(f'숙련견시원 ★MAX x{lookouts}',text)
                self.assertIn(f'{radar} ★4 이상 x1',text)
                self.assertIn(text,bot.ship_text(source,source['艦名']))

    def test_new_costs_are_not_applied_to_missing_wrong_or_changed_routes(self):
        import bot
        source=bot.SHIP_BY_GAME_ID[488]
        target=bot.SHIP_BY_GAME_ID[750]
        for changed,destination in ((source,None),(source,bot.SHIP_BY_GAME_ID[751]),
                                    (source | {'改装Lv':'94'},target),
                                    (source | {'改装弾薬':'999'},target),
                                    (source | {'改装設計図':'1'},target)):
            with self.subTest(changed=changed.get('改装Lv'),destination=destination is None):
                self.assertNotIn('요구 장비',materials.material_text(changed,destination))
        self.assertEqual(len(materials.supplement_reference()),4)

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
