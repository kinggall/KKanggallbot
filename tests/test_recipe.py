"""Secretary selection, real forward recipes, and Iris command integration."""
import importlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development import DevelopmentCatalog, pool_rate_details, resource_pool_type
from equipment_lookup import EquipmentCatalog


class RecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = DevelopmentCatalog(ROOT)
        cls.equipment = EquipmentCatalog(ROOT)
        cls.aliases = json.loads((ROOT / "data/ship_aliases.json").read_text(encoding="utf-8"))
        cls.translations = {"Richelieu": "리슐리외", "照月": "테루즈키", "秋月": "아키즈키",
                            "比叡": "히에이", "金剛": "콩고", "大鳳": "타이호",
                            "吹雪": "후부키", "Saratoga": "사라토가", "宗谷": "소야"}

    def reply(self, query):
        return self.catalog.recipe_reply(query, self.equipment, self.translations, self.aliases)

    def test_richelieu_example_including_full_output_order_and_failure(self):
        self.assertEqual(self.reply("리슐리외 10/30/20/10"),
                         "전함계-리슐리외급 [10/30/20/10]\n"
                         "· 14cm 단장포 - 2%\n· 15.2cm 단장포 - 6%\n"
                         "· 12.7cm 연장고각포 - 6%\n· 61cm 삼연장어뢰 - 4%\n"
                         "· 61cm 사연장어뢰 - 4%\n· 12.7mm 단장기총 - 2%\n"
                         "· 25mm 연장기총 - 4%\n· 25mm 삼연장기총 - 2%\n"
                         "· 25mm 단장기총 - 2%\n· 실패율 - 68%")
        self.assertEqual(self.reply("리슐 10/30/20/10"), self.reply("리슐리외 10/30/20/10"))
        self.assertEqual(self.reply("Richelieu 10 / 30 / 20 / 10"), self.reply("리슐리외 10/30/20/10"))

    def test_all_seven_akizuki_class_ships_and_fourteen_forms_use_class_pool(self):
        ships, _, metadata = self.catalog.ship_pools()
        members = [i for i in ships if metadata[str(i)]["ship_class"] == 54]
        self.assertEqual(set(members), {421, 330, 963, 422, 346, 423, 357, 968,
                                        532, 537, 533, 538, 1041, 1046})
        for ship_id in members:
            with self.subTest(ship_id=ship_id):
                self.assertEqual(self.catalog.secretary_pool(ship_id)["name"], "水雷系-秋月级")
                self.assertTrue(self.reply(f"#{ship_id} 10/30/20/10").startswith("수뢰계-아키즈키급 ["))
        self.assertEqual(self.reply("테루즈키 10/30/20/10"), self.reply("푸릉이 10/30/20/10"))
        self.assertIn("· 실패율 - 44%", self.reply("테루즈키 10/30/20/10"))

    def test_named_and_explicit_id_conditions_do_not_leak_into_base_forms(self):
        self.assertTrue(self.reply("히에이 10/30/20/10").startswith("전함계-콩고급"))
        self.assertTrue(self.reply("히에이 개1 10/30/20/10").startswith("전함계-콩고급"))
        self.assertTrue(self.reply("히에이 개2 10/30/20/10").startswith("전함계-히에이 개2"))
        self.assertTrue(self.reply("타이호 10/30/20/10").startswith("항모계-타이호 ["))
        self.assertTrue(self.reply("타이호 개1 10/30/20/10").startswith("항모계-타이호 개 ["))
        self.assertTrue(self.reply("후부키 개3 10/30/20/10").startswith("수뢰계-후부키 개2/시라유키 개2"))
        self.assertEqual(self.reply("불고기 개2 10/30/20/10"), self.reply("콩고 개2 10/30/20/10"))
        self.assertTrue(self.reply("사라토가 Mk.II 10/30/20/10").startswith("항모계-사라토가/호넷"))

    def test_same_name_soya_defaults_to_base_but_ids_select_distinct_types(self):
        self.assertEqual(self.catalog.resolve_secretary("소야", self.translations, self.aliases), [699])
        self.assertTrue(self.reply("소야 10/30/20/10").startswith("항모계-육군 함선/소야(특무함)"))
        self.assertTrue(self.reply("#645 10/30/20/10").startswith("수뢰계-소야(등대보급선/남극관측선)"))

    def test_all_866_forms_have_a_pool_and_valid_complete_distributions(self):
        ships, pools, _ = self.catalog.ship_pools()
        self.assertEqual(len(ships), 866)
        checked = set()
        for ship_id in ships:
            pool = self.catalog.secretary_pool(ship_id)
            self.assertIsNotNone(pool, ship_id)
            if pool["name"] in checked:
                continue
            checked.add(pool["name"])
            for resources in ((10, 10, 10, 10), (10, 30, 20, 10), (20, 60, 10, 110),
                              (240, 260, 10, 250), (239, 260, 10, 250), (300, 300, 300, 300),
                              (10, 10, 10, 11), (100, 100, 250, 250)):
                with self.subTest(ship_id=ship_id, resources=resources):
                    text = self.reply(f"#{ship_id} {'/'.join(map(str, resources))}")
                    self.assertIn("· 실패율 - ", text)
                    percentages = [int(n) for n in re.findall(r" - (\d+)%", text)]
                    self.assertEqual(sum(percentages), 100)
                    self.assertTrue(all(0 <= p <= 100 for p in percentages))
                    self.assertLess(len(text), 4096)

    def test_all_current_aliases_resolve_to_the_expected_base_family(self):
        ships, _, metadata = self.catalog.ship_pools()
        for canonical, names in self.aliases.items():
            expected = {metadata[str(i)]["base"] for i, s in ships.items() if s["艦名"] == canonical}
            for alias in [canonical, *names]:
                with self.subTest(alias=alias):
                    hits = self.catalog.resolve_secretary(alias, self.translations, self.aliases)
                    self.assertTrue(hits)
                    self.assertTrue({metadata[str(i)]["base"] for i in hits} <= expected)

    def test_minimum_resources_for_96_land_attacker_are_applied_per_component(self):
        def rates(resources):
            pool = self.catalog.secretary_pool(153)  # Taiho: carrier category.
            return pool_rate_details(self.catalog.ship_pools()[1], pool, resources)
        self.assertEqual(sum(rates((240, 260, 10, 250)).get(168, [])), 8)
        self.assertEqual(sum(rates((239, 260, 10, 250)).get(168, [])), 0)
        self.assertEqual(sum(rates((240, 259, 10, 250)).get(168, [])), 0)
        self.assertEqual(sum(rates((240, 260, 10, 249)).get(168, [])), 0)
        self.assertIn("96식 육공 - 8%", self.reply("타이호 240/260/10/250"))
        self.assertNotIn("96식 육공", self.reply("타이호 239/260/10/250"))

    def test_resource_type_ties_and_affordability(self):
        self.assertEqual(resource_pool_type((10, 10, 10, 11)), 1)
        self.assertEqual(resource_pool_type((10, 11, 10, 11)), 2)
        self.assertEqual(resource_pool_type((10, 11, 11, 11)), 3)
        self.assertNotIn("41cm 연장포 -", self.reply("불고기 10/30/20/10"))
        self.assertIn("41cm 연장포 - 8%", self.reply("불고기 10/201/200/10"))

    def test_malformed_resources_are_rejected_without_silently_changing_them(self):
        for query in ("", "리슐리외", "리슐리외 10/30/20", "리슐리외 10/30/20/10 extra",
                      "리슐리외 -10/30/20/10", "리슐리외 10.5/30/20/10"):
            self.assertTrue(self.reply(query).startswith("사용법:"))
        for query in ("리슐리외 9/30/20/10", "리슐리외 301/30/20/10"):
            self.assertIn("10~300", self.reply(query))
        self.assertIn("찾지 못했습니다", self.reply("없는함선 10/30/20/10"))

    def test_webhook_preserves_chat_id_and_help_lists_new_command(self):
        with patch("requests.get", side_effect=requests.RequestException("offline test")):
            bot = importlib.import_module("bot")
        with patch.dict(bot.SHIP_TRANSLATIONS, self.translations), patch.dict(bot.SHIP_ALIASES, self.aliases):
            for command in ("!레시피 리슐리외 10/30/20/10", "!레시피 푸릉이 10/30/20/10", "!레시피"):
                with self.subTest(command=command), patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
                    response = bot.app.test_client().post("/webhook", json={"msg": command, "room": None,
                                                                          "json": {"chat_id": "recipe-test"}})
                    self.assertEqual(response.status_code, 200)
                    send.assert_called_once()
                    self.assertEqual(send.call_args.kwargs["json"], {
                        "type": "text", "room": "recipe-test", "data": self.reply(command[len("!레시피"):])})
        self.assertIn("!레시피 [함선명] [연/탄/강/보]", bot.COMMANDS["!도움말"])


if __name__ == "__main__":
    unittest.main()
