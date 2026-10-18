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
                         "12cm 단장포\n· 화력 +1 / 대공 +1\n· 사거리 단")
        self.assertEqual(self.catalog.reply("12cm단장포"), self.catalog.reply("12cm 단장포"))
        self.assertNotIn("뇌장", self.catalog.reply("12cm단장포"))

    def test_aircraft_has_deployment_cost_and_radius_from_csv(self):
        self.assertEqual(self.catalog.reply("영식함전21형"),
                         "영식함전 21형\n· 대공 +5\n· 배치코스트 4(보키 72) / 행동반경 7")
        self.assertEqual(self.catalog.reply("영식 함상전투기 21형"), self.catalog.reply("零式艦戦21型"))

    def test_deployment_bauxite_uses_category_not_aircraft_name(self):
        # Four recon categories, both heavy bombers, and commonly confused aircraft.
        for item_id, cost, bauxite in ((25, 5, 20), (54, 9, 36), (138, 25, 100),
                                       (311, 7, 28), (395, 20, 180), (396, 21, 189),
                                       (169, 12, 216), (26, 6, 108), (69, 2, 36),
                                       (70, 3, 54), (561, 14, 252)):
            with self.subTest(item_id=item_id):
                self.assertIn(f"배치코스트 {cost}(보키 {bauxite})", self.catalog.describe(item_id))
        hiryu = self.catalog.items[403]["values"]
        self.assertIn(f"보키 {hiryu['配置コスト'] * 18}", self.catalog.describe(403))
        self.assertIn("배치코스트 12(보키 216) / 행동반경 9", self.catalog.describe(169))

    def test_all_263_deployment_cost_items_have_a_verified_category(self):
        counts = {4: 0, 9: 0, 18: 0}
        for item_id, item in self.catalog.items.items():
            values = item["values"]
            if not values["配置コスト"]:
                continue
            category = values["装備種3"]
            capacity = 4 if category in (9, 10, 41, 49) else 9 if category == 53 else 18
            counts[capacity] += 1
            with self.subTest(item_id=item_id):
                self.assertIn(f"보키 {values['配置コスト'] * capacity}", self.catalog.describe(item_id))
        self.assertEqual(counts, {4: 37, 9: 2, 18: 224})

    def test_unknown_deployment_category_does_not_guess_bauxite(self):
        with patch.dict(self.catalog.items[169]["values"], {"装備種3": 999}):
            self.assertIn("배치코스트 12(보키 계산 불가)", self.catalog.describe(169))

    def test_negative_values_and_long_ranges_are_preserved(self):
        self.assertIn("장갑 +7 / 회피 -2", self.catalog.describe(72))
        self.assertIn("사거리 초장", self.catalog.describe(9))
        self.assertIn("사거리 초장+", self.catalog.describe(561))

    def test_zero_stat_equipment_is_not_described_as_having_no_effect(self):
        self.assertEqual(self.catalog.describe(42), "응급수리요원\n· 능력치 없음(1회 부활 - 대파 상태)")
        self.assertEqual(self.catalog.describe(43), "응급수리여신\n· 능력치 없음(1회 부활 - 완전 회복)")
        self.assertEqual(self.catalog.describe(68), "대발동정\n· 능력치 없음")

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

    def test_zero_fighter_aliases_find_the_same_equipment(self):
        for alias in ("영식함전21형", "영전 21형", "0식 21형"):
            with self.subTest(alias=alias):
                self.assertEqual(self.catalog.search(alias), [20])
        for alias in ("영전 52형", "0식 52형"):
            with self.subTest(alias=alias):
                self.assertEqual(self.catalog.search(alias), [21])

    def test_aircraft_nicknames_keep_model_choices(self):
        self.assertEqual(self.catalog.search("플라잉팬케이크"), [375])
        self.assertEqual(self.catalog.search("팬케이크"), self.catalog.search("XF5U"))
        self.assertEqual(self.catalog.search("헬캣"), [205, 206, 254, 255])
        self.assertEqual(self.catalog.search("헬캣 5N"), [255])
        self.assertEqual(self.catalog.search("와일드캣 3"), [197])
        self.assertIn("검색 결과", self.catalog.reply("와일드캣"))
        self.assertEqual(self.catalog.search("콜세어 1D"), [233])
        self.assertEqual(self.catalog.search("커세어"), self.catalog.search("콜세어"))
        self.assertEqual(self.catalog.search("corsair"), self.catalog.search("콜세어"))
        self.assertEqual(self.catalog.search("커세어 1D"), [233])

    def test_model_letter_corrections_are_shared_with_fit_display(self):
        from fit_bonus import FitCatalog
        fit = FitCatalog(ROOT / "data")
        corrections = {338: "렛푸 개2무", 339: "렛푸 개2무 (1항전/숙련)",
                       348: "함재형 4식 20cm 대지분진포"}
        for item_id, name in corrections.items():
            with self.subTest(item_id=item_id):
                self.assertEqual(self.catalog.describe(item_id).splitlines()[0], name)
                self.assertEqual(fit.item_name(item_id), name)
                self.assertEqual(self.catalog.search(name), [item_id])
        for item_id in (303, 360, 361):
            with self.subTest(item_id=item_id):
                self.assertIn("Model 193", self.catalog.items[item_id]["name"])

    def test_main_gun_short_names_preserve_caliber_and_remodel(self):
        for query, item_id in (("12단장", 1), ("12단장포", 1), ("12 단장 개2", 293),
                               ("46삼연장", 9), ("46 3연장 개", 276), ("35.6연장개2", 329),
                               ("Bofors12단장양용", 584), ("12단장양용", 584)):
            with self.subTest(query=query):
                self.assertEqual(self.catalog.search(query), [item_id])
        self.assertEqual(self.catalog.search("203연장"), [])
        self.assertEqual(self.catalog.search("12연장"), [])
        self.assertEqual(self.catalog.search("35.6연장개3"), [502, 530])
        self.assertIn("검색 결과", self.catalog.reply("35.6연장개3"))

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
                for field, label in (("配置コスト", "배치코스트"), ("戦闘行動半径", "행동반경")):
                    if int(row[field]):
                        self.assertIn(f"{label} {int(row[field])}", description)
                    else:
                        self.assertNotIn(label, description)
                if not int(row['射程']):
                    self.assertNotIn("사거리", description)

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
