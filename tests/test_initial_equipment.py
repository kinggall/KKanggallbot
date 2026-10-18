"""Starting equipment CSV fidelity, verified stars, remodels and webhook tests."""
import csv
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from initial_equipment import InitialEquipmentCatalog, EMPTY_SLOTS


class InitialEquipmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = InitialEquipmentCatalog(ROOT)
        with (ROOT / "ships.csv").open(encoding="cp932", newline="") as file:
            cls.ships = {int(s["艦船ID"]): s for s in csv.DictReader(file) if 0 < int(s["艦船ID"]) < 1500}
        with patch("requests.get", side_effect=requests.RequestException("offline test")):
            cls.bot = importlib.import_module("bot")

    def test_yubari_all_forms_with_duplicate_starting_guns_and_empty_converts(self):
        reply = self.bot.build_initial_equipment_reply("유바리")
        self.assertEqual(reply,
                         "[미개장]\n· 14cm 단장포\n· 14cm 단장포\n\n"
                         "[개1]\n· 14cm 연장포\n· 12cm 단장고각포\n· 25mm 삼연장기총\n\n"
                         "[개2]\n· 초기 장비 없음\n\n[개2특]\n· 초기 장비 없음\n\n"
                         "[개2정]\n· 초기 장비 없음")

    def test_amatsukaze_unknown_csv_slots_are_completed_with_verified_stars(self):
        self.assertEqual(self.catalog.starting_items(self.ships[951]), [(266, 7), (87, 7), (87, 7)])
        text = self.bot.build_initial_equipment_reply("아마츠카제")
        self.assertIn("· 12.7cm 연장포 C형 개2 ★7", text)
        self.assertEqual(text.count("· 신형 고온 고압 보일러 ★7"), 2)

    def test_kongo_alias_and_verified_upgrade_suffix(self):
        text = self.bot.build_initial_equipment_reply("불고기")
        self.assertEqual(text, self.bot.build_initial_equipment_reply("콩고"))
        self.assertIn("[개2병]", text)
        self.assertIn("· 53cm 연장어뢰 ★6", text)
        self.assertEqual(text.split("[개2병]")[1].count("· 35.6cm 연장포 개\n"), 2)

    def test_name_changing_submarine_aliases_show_identical_full_family(self):
        self.assertEqual(self.bot.build_initial_equipment_reply("U-511"),
                         self.bot.build_initial_equipment_reply("로-500"))
        self.assertGreater(self.bot.build_initial_equipment_reply("U-511").count("["), 1)

    def test_all_866_forms_preserve_known_csv_item_order_and_every_supplement(self):
        self.assertEqual(len(self.ships), 866)
        used_supplements = set()
        for ship_id, ship in self.ships.items():
            expected = []
            extras = self.catalog.supplement.get(str(ship_id), {})
            for slot in range(1, int(ship["スロット数"]) + 1):
                raw = ship[f"初期装備{slot}"]
                if raw in EMPTY_SLOTS:
                    continue
                extra = extras.get(str(slot))
                stars = 0
                if raw == "???":
                    self.assertIsNotNone(extra, (ship_id, slot))
                    self.assertEqual(extra["csv"], raw)
                    item_id, stars = extra["equipment_id"], extra["stars"]
                else:
                    item_id = self.catalog.by_name[raw]
                    if extra:
                        self.assertEqual(extra["equipment_id"], item_id)
                        stars = extra["stars"]
                if extra:
                    used_supplements.add((str(ship_id), str(slot)))
                if item_id is not None:
                    expected.append((item_id, stars))
            with self.subTest(ship_id=ship_id):
                self.assertEqual(self.catalog.starting_items(ship), expected)
                text = self.catalog.form_text(ship, self.bot.ship_stage(ship))
                self.assertNotIn("미확인", text)
                self.assertEqual(text.count("초기 장비 없음"), int(not expected))
                self.assertEqual(text.count("★"), sum(stars > 0 for _, stars in expected))
        self.assertEqual(used_supplements, {(sid, slot) for sid, slots in self.catalog.supplement.items() for slot in slots})

    def test_unknown_or_stale_values_never_claim_no_starting_equipment(self):
        for raw in ("???", "CSV에 새로 추가된 장비"):
            ship = dict(self.ships[115], 初期装備1=raw, 初期装備2="(なし)")
            self.assertEqual(self.catalog.form_text(ship, "미개장"), "[미개장]\n· 초기 장비 미확인")
        ship = dict(self.ships[951], 初期装備1="새로운 장비")
        self.assertIsNone(self.catalog.starting_items(ship)[0])

    def test_explicit_csv_star_values_and_empty_slots_are_authoritative(self):
        for raw, expected in (("14cm単装砲 ★7", 7), ("14cm単装砲★max", 10)):
            ship = dict(self.ships[115], 初期装備1=raw, 初期装備2="(なし)")
            self.assertEqual(self.catalog.starting_items(ship), [(4, expected)])
        ship = dict(self.ships[951], 初期装備1="(なし)", 初期装備2="(なし)", 初期装備3="(なし)")
        self.assertEqual(self.catalog.form_text(ship, "개2"), "[개2]\n· 초기 장비 없음")

    def test_missing_unknown_name_and_webhook_reply_room(self):
        self.assertEqual(self.bot.build_initial_equipment_reply(""), "사용법: !초기장비 [칸무스]")
        self.assertIn("찾지 못했습니다", self.bot.build_initial_equipment_reply("없는칸무스"))
        self.assertIn("!초기장비 [함선명]", self.bot.COMMANDS["!도움말"])
        for message in ("!초기장비 유바리", "!초기장비 불고기", "!초기장비"):
            with self.subTest(message=message), patch.object(self.bot.requests, "post", return_value=Mock(status_code=200)) as send:
                response = self.bot.app.test_client().post("/webhook", json={"msg": message, "room": None,
                                                                          "json": {"chat_id": "starting-items-test"}})
                self.assertEqual(response.status_code, 200)
                send.assert_called_once()
                self.assertEqual(send.call_args.kwargs["json"], {
                    "type": "text", "room": "starting-items-test",
                    "data": self.bot.build_initial_equipment_reply(message[len("!초기장비"):])})


if __name__ == "__main__":
    unittest.main()
