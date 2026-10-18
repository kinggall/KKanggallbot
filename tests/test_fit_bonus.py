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
from fit_bonus import FitCatalog, RADARS, shorten_companion_conditions


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
        self.assertIn("2개 이상 장착 : 추가 화력+2 대공+2 (1회만)", text)
        self.assertIn("수상전탐 병용", text)
        self.assertIn("대공전탐 병용", text)

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
        self.assertIn("자체 인정", text)

    def test_shared_rules_compact_across_forms_without_losing_same_form_occurrences(self):
        block = ("삼식탄", ["· 화력+1 대공+1 (1회만)"])
        with patch.object(self.c, "blocks_for_ship", return_value=[block, block]):
            text = self.c.message("콩고", [(149, "개2"), (591, "개2병")])
        self.assertIn("[전체]", text)
        self.assertEqual(text.count("삼식탄:"), 2)

    def test_only_all_form_common_entries_are_grouped_and_forms_descend(self):
        common = ("전체 장비", ["· 화력+1 (1회만)"])
        partial = ("부분 공통 장비", ["· 화력+2 (1회만)"])
        own = ("최종 장비", ["· 화력+3 (1회만)"])
        source = {1: [common, partial], 2: [common, partial], 3: [common, own]}
        with patch.object(self.c, "blocks_for_ship", side_effect=lambda sid: source[sid]):
            text = self.c.message("콩고", [(1, "미개장"), (2, "개1"), (3, "개2")])
        self.assertTrue(text.startswith("[전체]\n"))
        self.assertEqual(text.count("전체 장비:"), 1)
        self.assertEqual(text.count("부분 공통 장비:"), 2)
        self.assertLess(text.index("[개2]"), text.index("[개1]"))
        self.assertLess(text.index("[개1]"), text.index("[미개장]"))
        self.assertNotIn("[미개장 / 개1]", text)

    def test_kongo_layout_footer_and_corrected_equipment_translation(self):
        forms = [(78, "미개장"), (209, "개1"), (149, "개2"), (591, "개2병")]
        text = self.c.message("콩고", forms)
        headers = [line for line in text.splitlines() if line.startswith("[")]
        self.assertEqual(headers, ["[전체]", "[개2병]", "[개2]", "[개1]", "[미개장]"])
        self.assertNotIn("콩고 피트", text)
        self.assertEqual(self.c.equipment["483"]["name_jp"], "三式弾改二")
        self.assertEqual(self.c.item_name(483), "3식탄 개2")
        self.assertIn("3식탄 개2", text)
        self.assertNotIn("3식 개2", text)
        self.assertIn("※ 개수보정은", text)
        self.assertIn("수상전탐 : 색적 5이상 / 대공전탐 : 대공 2이상 / 고명중전탐 : 명중 8이상", text)
        self.assertNotIn("≥", text)
        self.assertNotIn("※ ★보정", text)
        for stage in ("개2", "개1", "미개장"):
            section = text.split(f"[{stage}]\n", 1)[1].split("\n\n[", 1)[0]
            self.assertIn("1식 철갑탄 개: 화력+1 (1회만)", section)

    def test_companion_upgrade_labels_remain_anchored_to_the_companion(self):
        lines = next(lines for title, lines in self.c.blocks_for_ship(591) if title == self.c.item_name(530))
        self.assertIn(" - 53cm 연장어뢰 중 총 1개 이상 장착 : 뇌장+6 (1회만)", lines)
        self.assertIn("   - ★6 이상 총 1개 이상 장착 : 뇌장+1 (1회만)", lines)
        self.assertIn("   - ★8 이상 총 1개 이상 장착 : 명중+1 (1회만)", lines)
        self.assertIn("   - ★10 이상 총 1개 이상 장착 : 화력+1 (1회만)", lines)
        # A different companion or a break must restore its full name.
        original = [" - 어뢰A 중 총 1개 이상 장착 : 뇌장+1", " - 어뢰A 중 ★6 이상 총 1개 이상 장착 : 뇌장+1",
                    " - 어뢰B 중 ★8 이상 총 1개 이상 장착 : 뇌장+2", "★9: 추가 명중+1",
                    " - 어뢰B 중 ★10 이상 총 1개 이상 장착 : 화력+1"]
        compact = shorten_companion_conditions(original)
        self.assertIn("   - ★6 이상 총 1개 이상 장착 : 뇌장+1", compact)
        self.assertEqual(compact[2], original[2])
        self.assertEqual(compact[4], original[4])

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

    def test_all_csv_forms_render_without_missing_metadata_or_lost_conditions(self):
        with (ROOT / "ships.csv").open(encoding="cp932") as f:
            rows = [r for r in csv.DictReader(f) if int(r["艦船ID"]) <= 1500]
        self.assertEqual({r["艦船ID"] for r in rows}, set(self.c.ships))
        for row in rows:
            with self.subTest(ship=row["艦名"]):
                combined = self.c.message(row["艦名"], [(row["艦船ID"], "미개장")])
                self.assertTrue(combined)
                blocks = self.c.blocks_for_ship(row["艦船ID"])
                for title, lines in blocks:
                    for line in lines:
                        self.assertIn(line.removeprefix("· "), combined)

    def test_real_webhook_sends_entire_result_in_one_post(self):
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
                self.assertNotIn("다음: !피트", direct)
                self.assertIn("[개2]", direct)
                self.assertIn("[개2병]", direct)
                self.assertIn("(1회만)", direct)
                self.assertNotIn("장착 시 추가(1회)", direct)
                self.assertIn("사용법", bot.build_fit_reply(""))
                self.assertIn("찾지 못했습니다", bot.build_fit_reply("없는함선임"))
                with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
                    response = bot.app.test_client().post("/webhook", json={
                        "msg": "!피트 콩고", "json": {"chat_id": "fit-test"}})
                self.assertEqual(response.status_code, 200)
                send.assert_called_once()
                self.assertEqual(send.call_args.kwargs["json"]["room"], "fit-test")
                self.assertEqual(send.call_args.kwargs["json"]["data"], direct)
        self.assertIn("!피트", bot.COMMANDS["!도움말"])


if __name__ == "__main__":
    unittest.main()
