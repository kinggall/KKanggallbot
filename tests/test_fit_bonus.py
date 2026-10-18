"""EO fit regressions: real loadouts, count boundaries, and every radar condition."""
import copy
import csv
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fit_bonus import FitCatalog, RADARS, format_page, stats_text


class FitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = FitCatalog(ROOT / "data")

    def isolated(self, group, rule):
        cat = copy.copy(self.c)
        cat.groups = [dict(group, bonuses=[rule])]
        return cat

    def fixture(self, group, rule, count):
        """Find a real applicable ship and legal target, satisfying other prerequisites."""
        c = self.c
        for sid in c.ships:
            if not c.matches_ship(rule, sid):
                continue
            possible = [int(i) for i in c.equipment if c.can_equip(sid, int(i))]
            targets = [i for i in possible if c.trigger_matches(group, i)]
            if not targets:
                continue
            level = max(rule.get("level", 0), rule.get("requiresLevel", 0))
            items = [(targets[0], level)] * count
            if "requires" in rule:
                candidates = [i for i in possible if i in rule["requires"]]
                if not candidates:
                    continue
                missing = rule.get("requiresNum", 1) - sum(i in candidates and l >= rule.get("requiresLevel", 0) for i, l in items)
                items += [(candidates[0], rule.get("requiresLevel", 0))] * max(missing, 0)
            if "requiresType" in rule:
                candidates = [i for i in possible if c.equipment[str(i)]["type"] in rule["requiresType"]]
                if not candidates:
                    continue
                missing = rule.get("requiresNumType", 1) - sum(i in candidates for i, _ in items)
                items += [(candidates[0], 0)] * max(missing, 0)
            return sid, items, targets[0], possible
        self.fail(f"No real ship/equipment fixture for {group.get('ids', group.get('types'))}: {rule}")

    def test_kongo_sanshiki_is_once_not_per_item(self):
        expected = {"houg": 1, "tyku": 1}
        self.assertEqual(self.c.calculate(149, [(35, 0)]), expected)
        self.assertEqual(self.c.calculate(149, [(35, 0), (35, 0)]), expected)

    def test_kongo_gun_surface_radar_is_once_even_with_two_guns(self):
        self.assertEqual(self.c.calculate(149, [(289, 0)]), {"houg": 2, "tyku": 1})
        self.assertEqual(self.c.calculate(149, [(289, 0), (29, 0)]),
                         {"houg": 4, "tyku": 1, "kaih": 2})
        self.assertEqual(self.c.calculate(149, [(289, 0), (289, 0), (29, 0)]),
                         {"houg": 6, "tyku": 2, "kaih": 2})

    def test_naganami_two_guns_and_both_radar_categories(self):
        self.assertEqual(self.c.calculate(543, [(366, 0)]),
                         {"houg": 4, "kaih": 1, "tyku": 3, "houm": 1})
        self.assertEqual(self.c.calculate(543, [(366, 0), (366, 0)]),
                         {"houg": 9, "kaih": 2, "tyku": 5, "houm": 1})
        self.assertEqual(self.c.calculate(543, [(366, 0), (366, 0), (29, 0)]),
                         {"houg": 11, "kaih": 4, "tyku": 5, "houm": 3, "raig": 4})
        # GFCS is both surface and air radar: both conditions may apply once.
        self.assertEqual(self.c.calculate(543, [(366, 0), (366, 0), (307, 0)]),
                         {"houg": 12, "kaih": 7, "tyku": 10, "houm": 4, "raig": 4})
        text = "\n".join(line for title, lines in self.c.blocks_for_ship(543)
                         if title == self.c.item_name(366) for line in lines)
        self.assertIn("2개 이상 장착 시 추가(1회): 화력 +2 / 대공 +2", text)
        self.assertIn("수상전탐 함께 장착", text)
        self.assertIn("대공전탐 함께 장착", text)

    def test_count_requires_only_qualifying_upgraded_items(self):
        group = next(g for g in self.c.groups if g.get("ids") == [285])
        rule = next(r for r in group["bonuses"] if r.get("num") == 2 and r.get("level") == 10)
        c = self.isolated(group, rule)
        sid, _, target, _ = self.fixture(group, rule, 2)
        self.assertEqual(c.calculate(sid, [(target, 10), (target, 9)]), {})
        self.assertEqual(c.calculate(sid, [(target, 10), (target, 10)]), rule["bonus"])
        self.assertIn("★10 이상 장비 기준 · 2개 이상", c.condition_text(rule, "bonus"))

    def test_all_48_multi_item_rule_boundaries(self):
        checked = 0
        for group in self.c.groups:
            for rule in group["bonuses"]:
                number = rule.get("num", 1)
                if number < 2:
                    continue
                with self.subTest(ids=group.get("ids"), rule=rule):
                    c = self.isolated(group, rule)
                    sid, items, target, possible = self.fixture(group, rule, number)
                    for field in RADARS:
                        if field in rule and not any(c.is_radar(i, field) for i, _ in items):
                            radar = next(i for i in possible if c.is_radar(i, field)
                                         and not c.trigger_matches(group, i))
                            items.append((radar, 0))
                    expected = dict(rule.get("bonus", {}))
                    for field in RADARS:
                        if field in rule and any(c.is_radar(i, field) for i, _ in items):
                            for stat, value in rule[field].items():
                                expected[stat] = expected.get(stat, 0) + value
                    self.assertTrue(expected)
                    # Only the selected rule is evaluated; its threshold bonus is once.
                    self.assertEqual(c.calculate(sid, items), expected)
                    below = list(items)
                    below.remove((target, max(rule.get("level", 0), rule.get("requiresLevel", 0))))
                    self.assertEqual(c.calculate(sid, below), {})
                    self.assertEqual(c.calculate(sid, items + [(target, 10)]), expected)
                    self.assertIn(f"{number}개 이상 장착 시 추가(1회)", c.condition_text(rule, "bonus"))
                    checked += 1
        self.assertEqual(checked, 48)

    def test_all_118_radar_conditions_are_once_and_keep_prerequisites(self):
        checked = 0
        for group in self.c.groups:
            for source in group["bonuses"]:
                for field in RADARS:
                    if field not in source:
                        continue
                    rule = {k: v for k, v in source.items() if k not in {"bonus", *RADARS} or k == field}
                    with self.subTest(ids=group.get("ids"), field=field, rule=rule):
                        c = self.isolated(group, rule)
                        sid, items, _, possible = self.fixture(group, rule, rule.get("num", 1))
                        radar = next(i for i in possible if c.is_radar(i, field))
                        self.assertEqual(c.calculate(sid, items + [(radar, 0)]), rule[field])
                        self.assertEqual(c.calculate(sid, items + [(radar, 0), (radar, 0)]), rule[field])
                        # Remove radar gear; a non-radar cannot activate a radar condition.
                        without_radar = [(i, l) for i, l in items if not c.is_radar(i, field)]
                        self.assertEqual(c.calculate(sid, without_radar), {})
                        label = c.condition_text(rule, field)
                        self.assertIn(RADARS[field][0] + " 함께 장착", label)
                        self.assertIn("1회", label)
                        checked += 1
        self.assertEqual(checked, 118)

    def test_radar_target_can_fulfil_its_own_radar_requirement(self):
        # Okinami Kai Ni has a category-wide radar bonus: the target itself counts.
        text = "\n".join(line for title, lines in self.c.blocks_for_ship(569)
                         if "전탐" in title and "종류 공통" in title for line in lines)
        self.assertIn("대상 장비 자체도 인정", text)

    def test_companion_does_not_bypass_own_equipment_upgrade_requirement(self):
        checked = 0
        for group in self.c.groups:
            for rule in group["bonuses"]:
                if not (rule.get("level") and ("requires" in rule or "requiresType" in rule) and "num" not in rule):
                    continue
                with self.subTest(ids=group.get("ids"), rule=rule):
                    c = self.isolated(group, rule)
                    sid, items, target, _ = self.fixture(group, rule, 1)
                    self.assertTrue(c.calculate(sid, items))
                    below = [(i, rule["level"] - 1 if c.trigger_matches(group, i) else l) for i, l in items]
                    self.assertEqual(c.calculate(sid, below), {})
                    checked += 1
        self.assertEqual(checked, 10)

    def test_all_csv_forms_render_without_missing_metadata_or_overflow(self):
        with (ROOT / "ships.csv").open(encoding="cp932") as f:
            rows = [r for r in csv.DictReader(f) if int(r["艦船ID"]) <= 1500]
        self.assertEqual({r["艦船ID"] for r in rows}, set(self.c.ships))
        for row in rows:
            with self.subTest(ship=row["艦名"]):
                pages = self.c.pages([(row["艦船ID"], row["艦名"])])
                self.assertTrue(pages)
                self.assertTrue(all(len(page) < 2400 for page in pages))
                blocks = self.c.blocks_for_ship(row["艦船ID"])
                combined = "\n".join(pages)
                for title, lines in blocks:
                    self.assertIn(title, combined)
                    for line in lines:
                        self.assertIn(line, combined)

    def test_real_webhook_alias_paging_and_usage(self):
        with patch("requests.get", side_effect=requests.RequestException("offline import")):
            bot = importlib.import_module("bot")
        with (ROOT / "ships.csv").open(encoding="cp932") as f:
            ships = [r for r in csv.DictReader(f) if int(r["艦船ID"]) <= 1500]
        aliases = json.loads((ROOT / "data/ship_aliases.json").read_text(encoding="utf-8"))
        with patch.multiple(bot, SHIPS=ships, SHIP_TRANSLATIONS={}, SHIP_ALIASES=aliases,
                            SHIP_BY_GAME_ID={int(r["艦船ID"]): r for r in ships}):
            with patch.object(bot, "SHIP_GRAPH", bot.build_ship_graph()):
                direct = bot.build_fit_reply("콩고")
                alias = bot.build_fit_reply("불고기")
                self.assertEqual(direct.split("\n", 1)[1].replace("콩고", "QUERY"),
                                 alias.split("\n", 1)[1].replace("불고기", "QUERY").replace("콩고", "QUERY"))
                self.assertIn("다음: !피트 콩고 2", direct)
                self.assertNotEqual(direct, bot.build_fit_reply("콩고 2"))
                self.assertIn("페이지는", bot.build_fit_reply("콩고 999"))
                self.assertIn("사용법", bot.build_fit_reply(""))
                self.assertIn("찾지 못했습니다", bot.build_fit_reply("없는함선임"))
                with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
                    response = bot.app.test_client().post("/webhook", json={
                        "msg": "!피트 콩고", "json": {"chat_id": "fit-test"}})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(send.call_args.kwargs["json"]["room"], "fit-test")
                self.assertEqual(send.call_args.kwargs["json"]["data"], direct)
        self.assertIn("!피트", bot.COMMANDS["!도움말"])


if __name__ == "__main__":
    unittest.main()
