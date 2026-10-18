"""Recipe presentation and command integration checks; all network I/O is mocked."""
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import development
from equipment_lookup import EquipmentCatalog


class DevelopmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = development.DevelopmentCatalog(ROOT)
        cls.equipment = EquipmentCatalog(ROOT)

    def reply(self, query):
        return self.catalog.reply(query, self.equipment)

    def test_zuiun_matches_requested_optimal_and_unrestricted_fallback(self):
        self.assertEqual(self.reply("즈이운"),
                         "[최적]\n· 비서함 : 잠수계-스캠프/새먼\n· 20 / 30 / 10 / 50\n"
                         "· 개발 확률 10% / 실패율 34%\n"
                         "[범용]\n· 비서함 : 잠수계\n· 20 / 30 / 10 / 50\n"
                         "· 개발 확률 10% / 실패율 32%")

    def test_41cm_gun_matches_requested_example(self):
        self.assertEqual(self.reply("41cm연장포"),
                         "[최적]\n· 비서함 : 전함계-콩고형\n· 10 / 201 / 200 / 10\n"
                         "· 개발 확률 8% / 실패율 36%\n"
                         "[범용]\n· 비서함 : 전함계\n· 10 / 201 / 200 / 10\n"
                         "· 개발 확률 8% / 실패율 28%")

    def test_names_aliases_short_gun_names_and_ids_use_same_catalog(self):
        self.assertEqual(self.reply("#7"), self.reply("35.6연장"))
        self.assertEqual(self.reply("#26"), self.reply("瑞雲"))
        for name in ("영전 21형", "0식 21형", "零式艦戦21型"):
            self.assertEqual(self.reply(name), self.reply("#20"))
        self.assertIn("개발 확률 10%", self.reply("#7"))

    def test_candidates_keep_non_developable_items_and_offer_development_ids(self):
        reply = self.reply("와일드캣")
        self.assertIn("검색 결과 4개", reply)
        self.assertIn("(#197)", reply)
        self.assertIn("(#277)", reply)  # Not developable; still a valid equipment candidate.
        self.assertIn("번호 검색 예: !개발 #197", reply)
        self.assertNotIn("!장비", reply)
        self.assertIn("검색 결과 23개", self.reply("제로센"))

    def test_non_developable_unknown_and_empty_query(self):
        self.assertEqual(self.reply("#503"), "35.6cm 연장포 개4\n· 개발불가")
        self.assertEqual(self.reply("플라잉팬케이크"), "XF5U\n· 개발불가")
        self.assertEqual(self.reply("없는장비"), "'없는장비' 장비를 찾지 못했습니다.")
        self.assertIn("찾지 못했습니다", self.reply("#1501"))
        self.assertEqual(self.reply(""), "사용법: !개발 장비명 / !개발 #장비번호")

    def test_generic_top_result_is_not_duplicated_and_special_only_has_no_fallback(self):
        generic_id = next(i for i in self.equipment.items if (r := self.catalog.recipes(i))
                          and r[0].pool_name in development.GENERAL_POOLS)
        self.assertNotIn("[범용]", self.reply(f"#{generic_id}"))
        special_id = next(i for i in self.equipment.items if (r := self.catalog.recipes(i))
                          and not any(x.pool_name in development.GENERAL_POOLS for x in r))
        self.assertNotIn("[범용]", self.reply(f"#{special_id}"))
        self.assertIn("[최적]", self.reply(f"#{special_id}"))

    def test_every_normal_equipment_has_consistent_resource_and_probability_bounds(self):
        developable = 0
        for item_id in self.equipment.items:
            recipes = self.catalog.recipes(item_id)
            if not recipes:
                continue
            developable += 1
            for recipe in recipes:
                with self.subTest(item_id=item_id, pool=recipe.pool_name):
                    self.assertTrue(0 < recipe.probability <= 100)
                    self.assertTrue(0 <= recipe.failure <= 100 - recipe.probability)
                    self.assertTrue(all(r >= max(10, b * 10) for r, b in
                                        zip(recipe.resources, self.catalog.equipment[item_id])))
                    self.assertTrue(all(10 <= r <= 999 for r in recipe.resources))
            reply = self.reply(f"#{item_id}")
            self.assertEqual(reply.count("[최적]"), 1)
            self.assertLessEqual(reply.count("[범용]"), 1)
            self.assertNotIn("其它", reply)
        self.assertEqual(developable, 102)

    def test_only_invalid_recipe_is_removed_and_201_still_has_valid_recipes(self):
        recipes = self.catalog.recipes(201)
        self.assertTrue(recipes)
        self.assertFalse(any(r.pool_name == "水雷系-32驱改二" and r.pool_id == 1 for r in recipes))
        reply = self.reply("#201")
        self.assertIn("[최적]", reply)
        self.assertIn("개발 확률", reply)
        self.assertNotIn("실패율 98%", reply)
        self.assertNotIn("확인이 필요합니다", reply)

    def test_96_land_attacker_special_resources(self):
        recipes = self.catalog.recipes(168)
        self.assertTrue(recipes)
        for recipe in recipes:
            self.assertGreaterEqual(recipe.resources[0], 240)
            self.assertGreaterEqual(recipe.resources[1], 260)
            self.assertGreaterEqual(recipe.resources[3], 250)
            self.assertEqual(recipe.probability, 8)

    def test_sort_retains_upstream_near_equal_resource_tie_rule(self):
        a = development.Recipe("a", 1, (10, 10, 10, 11), 10, 60)
        b = development.Recipe("b", 1, (10, 10, 10, 10), 10, 50)
        self.assertLess(development.compare_recipes(a, b), 0)
        self.assertLess(development.compare_recipes(b, development.Recipe("c", 1, (10, 10, 10, 12), 10, 90)), 0)

    def test_webhook_replies_once_to_original_room_and_help_lists_command(self):
        with patch("requests.get", side_effect=requests.RequestException("offline test")):
            bot = importlib.import_module("bot")
        client = bot.app.test_client()
        for command in ("!개발 즈이운", "!개발 #7", "!개발 #503", "!개발 와일드캣", "!개발"):
            with self.subTest(command=command), patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
                response = client.post("/webhook", json={"msg": command, "room": None,
                                                       "json": {"chat_id": "development-test"}})
                self.assertEqual(response.status_code, 200)
                send.assert_called_once()
                self.assertEqual(send.call_args.kwargs["json"], {
                    "type": "text", "room": "development-test", "data": self.reply(command[len("!개발"):])})
        self.assertIn("!개발 [장비명]", bot.COMMANDS["!도움말"])
        with patch.object(bot.requests, "post") as send:
            client.post("/webhook", json={"msg": "!레시피 항모 10 30 30 20", "json": {"chat_id": "test"}})
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
