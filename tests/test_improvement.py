"""EO upgrade data, current/target star boundaries, branches and webhook tests."""
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from improvement import ImprovementCatalog, cost_at, star_ranges, DAY_ORDER


class ImprovementTests(unittest.TestCase):
    def phase(self, text, label):
        lines = text.splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(label + " -"))
        result = [lines[index]]
        if index + 1 < len(lines) and lines[index + 1].startswith(" · 소모아이템 :"):
            result.append(lines[index + 1])
        return "\n".join(result)

    @classmethod
    def setUpClass(cls):
        cls.catalog = ImprovementCatalog(ROOT)
        with patch("requests.get", side_effect=requests.RequestException("offline test")):
            cls.bot = importlib.import_module("bot")

    def test_source_snapshot_matches_pinned_original(self):
        self.assertEqual(hashlib.sha256((ROOT / "data/equipment_upgrades.json").read_bytes()).hexdigest(),
                         "927210efa30abcb2d00030659c0be2ee529ccbaa4817332545313abb9a484af3")
        self.assertEqual(len(self.catalog.upgrades), 385)

    def test_extra_costs_use_target_level_and_add_to_existing_materials(self):
        costs = deepcopy(self.catalog.upgrades[1]["improvement"][0]["costs"])
        costs["extra"] = [{"levels": [7], "equips": [{"id": 1, "eq_count": 3}],
                           "consumable": [{"id": 104, "eq_count": 2}]},
                          {"levels": [7, 255], "equips": [], "consumable": [{"id": 104, "eq_count": 1}]}]
        before = deepcopy(costs)
        self.assertEqual(cost_at(costs, 6)[4], ((1, 1),))
        self.assertEqual(cost_at(costs, 7)[4], ((1, 5),))
        self.assertEqual(cost_at(costs, 7)[5], ((104, 3),))
        self.assertEqual(cost_at(costs, 8)[5], ())
        self.assertEqual(cost_at(costs, 255)[5], ((104, 1),))
        self.assertEqual(costs, before)  # No cumulative mutation across repeated lookups.

    def test_current_star_ranges_split_only_where_complete_cost_changes(self):
        costs = self.catalog.upgrades[573]["improvement"][0]["costs"]
        self.assertEqual([(a, b) for a, b, _ in star_ranges(costs)], [(0, 5), (6, 6), (7, 8), (9, 9)])
        text = self.bot.build_improvement_reply("#573")
        self.assertIn("★7~8 -", text)
        self.assertIn("공창자원 1개", self.phase(text, "★9"))
        self.assertNotIn("공창자원", self.phase(text, "★7~8"))

    def test_overseas_technology_and_each_special_material_boundary(self):
        text = self.bot.build_improvement_reply("콜세어 1D")
        self.assertIn("해외함 최신기술 1개", self.phase(text, "★7~9"))
        self.assertNotIn("해외함 최신기술", self.phase(text, "★6"))
        radar = self.bot.build_improvement_reply("#574")
        self.assertIn("공창자원 2개", self.phase(radar, "★7~8"))
        self.assertIn("신형병장자재 2개", self.phase(radar, "★9"))
        self.assertNotIn("공창자원", self.phase(radar, "★9"))

    def test_sonar_conversion_keeps_result_stars_cost_and_helpers_separate(self):
        text = self.bot.build_improvement_reply("#46")
        normal, first, second = text.split("※ 개수변환")
        self.assertIn("1 - 3식 수중청음기 ★3", first)
        self.assertIn("2 - 4식 수중청음기", second)
        self.assertIn("93식 수중청음기 2개", first)
        self.assertIn("3식 수중청음기 2개", second)
        self.assertIn("이스즈 개2 (월)", first)
        self.assertIn("이스즈 개2 (목금)", second)
        self.assertNotIn("시구레", first)
        self.assertIn("시구레", second)
        self.assertEqual(normal.count("★0~5"), 1)

    def test_branch_specific_arsenal_materials_are_not_leaked(self):
        text = self.bot.build_improvement_reply("#63")
        first, second = text.split("※ 개수변환1")[1].split("※ 개수변환2")
        self.assertNotIn("공창자원", first)
        self.assertIn("공창자원 6개", second)
        self.assertNotIn("사기리", first)
        self.assertIn("사기리", second)

    def test_regular_costs_are_split_when_helper_routes_consume_different_guns(self):
        text = self.bot.build_improvement_reply("#121")
        group1, rest = text.split("[개수 경로 1]")[1].split("[개수 경로 2]")
        group2 = rest.split("※ 개수변환1")[0]
        self.assertIn("10cm 연장고각포 1개", group1)
        self.assertNotIn("12.7cm 연장고각포 1개", group1)
        self.assertIn("12.7cm 연장고각포 1개", group2)
        self.assertNotIn("10cm 연장고각포 1개", group2)
        self.assertIn("마야 개2", group2)
        self.assertNotIn("마야 개2", group1)
        self.assertIn("개수 경로 1에서 변환", text)
        self.assertIn("개수 경로 2에서 변환", text)

    def test_every_route_covers_exactly_ten_current_stars_without_missing_extras(self):
        c = self.catalog
        known_ships = set(self.bot.SHIP_BY_GAME_ID)
        route_count = 0
        for row in c.upgrades.values():
            for route in row["improvement"]:
                route_count += 1
                costs = route["costs"]
                ranges = star_ranges(costs)
                flattened = [(star, cost) for a, b, cost in ranges for star in range(a, b + 1)]
                self.assertEqual([s for s, _ in flattened], list(range(10)))
                for star, cost in flattened:
                    self.assertEqual(cost, cost_at(costs, star + 1))
                for left, right in zip(ranges, ranges[1:]):
                    self.assertNotEqual(left[2], right[2])
                for h in route["helpers"]:
                    self.assertTrue(set(h["ship_ids"]) <= known_ships)
                    self.assertTrue(set(h["days"]) <= set(DAY_ORDER))
        self.assertEqual(route_count, 417)
        for item_id in c.equipment.items:
            reply = self.bot.build_improvement_reply(f"#{item_id}")
            self.assertTrue(reply.startswith(c.item_name(item_id)))
            self.assertLess(len(reply), 4096)

    def test_equipment_alias_id_candidates_usage_and_missing_data(self):
        self.assertEqual(self.bot.build_improvement_reply("영전 21형"), self.bot.build_improvement_reply("#20"))
        self.assertIn("번호 검색 예: !개수 #", self.bot.build_improvement_reply("와일드캣"))
        self.assertEqual(self.bot.build_improvement_reply(""), "사용법: !개수 [장비명]")
        self.assertIn("찾지 못했습니다", self.bot.build_improvement_reply("없는장비"))
        self.assertIn("개수 정보 없음", self.bot.build_improvement_reply("#42"))
        self.assertIn("○ 2번함\n - 정보 없음", self.bot.build_improvement_reply("#2"))

    def test_requested_127mm_layout_whitespace_and_single_conversion_title(self):
        self.assertEqual(self.bot.build_improvement_reply("#2"),
                         "12.7cm 연장포\n"
                         "★0~5 - 자재 1 / 나사 1 (확정 시 2 / 2)\n"
                         "★6~9 - 자재 1 / 나사 1 (확정 시 2 / 2)\n"
                         " · 소모아이템 : 12.7cm 연장포 1개\n\n"
                         "○ 2번함\n - 정보 없음\n\n"
                         "※ 개수변환 - 12.7cm 연장포 B형 개2\n"
                         "★max - 자재 2 / 나사 3 (확정 시 3 / 6)\n"
                         " · 소모아이템 : 12.7cm 연장포 2개\n\n"
                         "○ 2번함\n - 정보 없음")

    def test_radar_helpers_group_only_identical_weekdays_in_remodel_order(self):
        text = self.bot.build_improvement_reply("#27")
        self.assertEqual(text.count(" - 시구레[미개장/개1] (금토일)"), 2)
        self.assertEqual(text.count(" - 시구레[개2/개3] (토일)"), 2)
        self.assertLess(text.index("시구레[미개장/개1]"), text.index("시구레[개2/개3]"))
        self.assertIn(" - 아키즈키[미개장/개1/개2] (화수목)", text)
        self.assertNotIn("시구레[미개장/개1/개2/개3]", text)
        self.assertNotIn("비서함", text)
        self.assertNotIn("자원:", text)
        self.assertNotIn("개수변환1", text)

    def test_webhook_replies_once_to_original_room_and_help_lists_command(self):
        for command in ("!개수 #46", "!개수 콜세어 1D", "!개수"):
            with self.subTest(command=command), patch.object(self.bot.requests, "post", return_value=Mock(status_code=200)) as send:
                response = self.bot.app.test_client().post("/webhook", json={"msg": command, "room": None,
                                                                          "json": {"chat_id": "improvement-test"}})
                self.assertEqual(response.status_code, 200)
                send.assert_called_once()
                self.assertEqual(send.call_args.kwargs["json"], {
                    "type": "text", "room": "improvement-test",
                    "data": self.bot.build_improvement_reply(command[len("!개수"):])})
        self.assertIn("!개수 [장비명]", self.bot.COMMANDS["!도움말"])


if __name__ == "__main__":
    unittest.main()
