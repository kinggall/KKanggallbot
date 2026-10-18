"""Equipment encyclopedia checks, including all normal equipment IDs."""
import csv
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equipment_lookup import EquipmentCatalog, STATS, normalize


class EquipmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = EquipmentCatalog(ROOT)

    def test_12cm_single_gun_includes_all_requested_fields(self):
        self.assertEqual(self.catalog.reply("12cm단장포"),
                         "12cm 단장포\n화력 +1 / 대공 +1\n사거리 단 / 배치코스트 0 / 행동반경 0")
        self.assertEqual(self.catalog.reply("12cm단장포"), self.catalog.reply("12cm 단장포"))
        self.assertNotIn("뇌장", self.catalog.reply("12cm단장포"))

    def test_aircraft_has_deployment_cost_and_radius_from_csv(self):
        self.assertEqual(self.catalog.reply("영식함전21형"),
                         "영식함전 21형\n대공 +5\n사거리 없음 / 배치코스트 4 / 행동반경 7")
        self.assertEqual(self.catalog.reply("영식 함상전투기 21형"), self.catalog.reply("零式艦戦21型"))

    def test_negative_values_and_long_ranges_are_preserved(self):
        self.assertIn("장갑 +7 / 회피 -2", self.catalog.describe(72))
        self.assertIn("사거리 초장 /", self.catalog.describe(9))
        self.assertIn("사거리 초장+ /", self.catalog.describe(561))

    def test_zero_stat_equipment_is_not_described_as_having_no_effect(self):
        self.assertIn("기본 능력치: 모두 0", self.catalog.describe(42))
        self.assertIn("사거리 없음 / 배치코스트 0 / 행동반경 0", self.catalog.describe(42))

    def test_korean_japanese_unicode_and_accent_name_variants(self):
        self.assertEqual(self.catalog.reply("46cm3연장포"), self.catalog.reply("46cm 삼연장포"))
        self.assertEqual(self.catalog.reply("１２cm 단장포"), self.catalog.reply("12cm단장포"))
        self.assertEqual(self.catalog.reply("wg42 (wurfgerat 42)"), self.catalog.reply("WG42 (Wurfgerät 42)"))
        self.assertEqual(normalize("F6F-5"), normalize("f6f５"))

    def test_ambiguous_partial_name_shows_candidates_not_arbitrary_stats(self):
        self.assertEqual(self.catalog.search("12cm単装砲"), [1])
        text = self.catalog.reply("12cm")
        self.assertIn("검색 결과", text)
        self.assertIn("12cm 단장포 (#1)", text)
        self.assertIn("외 1개", text)
        self.assertNotIn("화력 +1", text)
        self.assertEqual(sum(line.startswith("· ") for line in text.splitlines()), 10)

    def test_no_name_no_match_id_query_and_enemy_exclusion(self):
        self.assertEqual(self.catalog.reply(""), "사용법: !장비 장비명")
        self.assertIn("찾지 못했습니다", self.catalog.reply("없는장비임"))
        self.assertEqual(self.catalog.reply("#1"), self.catalog.reply("12cm단장포"))
        self.assertEqual(self.catalog.search("#1501"), [])
        self.assertEqual(self.catalog.search("深海"), [])

    def test_existing_equipment_translation_override_is_used(self):
        text = self.catalog.reply("삼식탄 개2")
        self.assertTrue(text.startswith("3식탄 개2\n"))
        self.assertEqual(text, self.catalog.reply("三式弾改二"))
        self.assertNotIn("3식 개2", text)

    def test_all_584_normal_items_use_csv_values_and_remain_searchable(self):
        with (ROOT / "equipments.csv").open(encoding="cp932", newline="") as file:
            rows = [r for r in csv.DictReader(file) if 0 < int(r["装備ID"]) < 1500]
        self.assertEqual(len(rows), 584)
        self.assertEqual({int(r["装備ID"]) for r in rows}, set(self.catalog.items))
        for row in rows:
            item_id = int(row["装備ID"])
            with self.subTest(item_id=item_id):
                self.assertIn(item_id, self.catalog.search(row["装備名"]))
                self.assertIn(item_id, self.catalog.search(self.catalog.items[item_id]["name"]))
                description = self.catalog.describe(item_id)
                for field, label in STATS:
                    value = int(row[field])
                    if value:
                        self.assertIn(f"{label} {value:+d}", description)
                    else:
                        self.assertNotIn(f"{label} +0", description)
                self.assertIn(f"배치코스트 {int(row['配置コスト'])}", description)
                self.assertIn(f"행동반경 {int(row['戦闘行動半径'])}", description)

    def test_webhook_sends_one_response_to_original_chat_and_help_lists_command(self):
        with patch("requests.get", side_effect=requests.RequestException("offline import")):
            bot = importlib.import_module("bot")
        client = bot.app.test_client()
        with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
            response = client.post("/webhook", json={"msg": "!장비 12cm단장포", "room": None,
                                                   "json": {"chat_id": "equipment-test"}})
        self.assertEqual(response.status_code, 200)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["json"], {
            "type": "text", "room": "equipment-test", "data": self.catalog.reply("12cm단장포")})
        self.assertIn("!장비 [장비명]", bot.COMMANDS["!도움말"])
        with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
            response = client.post("/webhook", json={"msg": "!장비", "json": {"chat_id": "equipment-test"}})
        self.assertEqual(send.call_args.kwargs["json"]["data"], "사용법: !장비 장비명")


if __name__ == "__main__":
    unittest.main()
