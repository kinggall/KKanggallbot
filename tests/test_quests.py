"""Quest IDs, source precedence, graph integrity and actual webhook replies."""
import hashlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import requests
import quests

ROOT = Path(__file__).resolve().parents[1]


class QuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = quests.QuestCatalog(ROOT)

    def test_b100_actual_reply_and_case_insensitive_number(self):
        expected = '''B100: 증강 해상호위총대, 발묘하라! (단발)

[임무 내용]
· 경항모/항순 1 + 경순 1 + 구축/해방 2 + 자유 2
· 2-2/2-3/2-4/2-5 보스 A승 이상 각 1회

[보상]
· 연료 700
· 선택: 훈장 / 신형포공병장자재 (택1)

[선행임무](검증중)
Bw5 + B98'''
        self.assertEqual(self.catalog.reply(" b100 "), expected)
        self.assertEqual(self.catalog.reply("B100"), expected)
        self.assertEqual(self.catalog.by_code["b100"], "857")

    def test_single_name_and_multiple_keyword_results(self):
        self.assertEqual(self.catalog.reply("증강 해상호위총대"), self.catalog.reply("B100"))
        result = self.catalog.reply("증강")
        self.assertIn("검색 결과 4개", result)
        for code in ("B62", "B83", "B100", "Fy4"):
            self.assertIn(f"({code})", result)
        # This shorter phrase REALLY matches two quests, not just B100.
        result = self.catalog.reply("해상호위총대")
        self.assertIn("검색 결과 2개", result)
        self.assertIn("(D23)", result)

    def test_predecessors_are_real_ids_and_successors_reverse_the_edges(self):
        self.assertEqual(self.catalog.items["857"]["prereqs"], [228, 855])
        self.assertEqual(self.catalog.after["855"], {"856", "857", "921"})
        output = self.catalog.reply("B98")
        self.assertIn("B99 / B100 / B149", output)
        # F19/F20 records are corrected, but references use actual game IDs.
        self.assertEqual(self.catalog.by_code["f19"], "623")
        self.assertEqual(self.catalog.by_code["f20"], "622")
        self.assertIn("97식 함상공격기", self.catalog.items["623"]["name_ko"])
        self.assertIn("F19", self.catalog.reply("F88").split("[선행임무]")[1])
        self.assertIn("F20", self.catalog.reply("F127").split("[선행임무]")[1])

    def test_graph_has_no_cycles_and_all_ids_have_external_codes(self):
        visited = set()

        def visit(key, stack):
            self.assertNotIn(key, stack, f"cyclic prerequisites: {stack}")
            if key in visited:
                return
            for before in self.catalog.items[key]["prereqs"]:
                self.assertIn(str(before), self.catalog.codes)
                self.assertIn(key, self.catalog.after[str(before)])
                if str(before) in self.catalog.items:
                    visit(str(before), stack | {key})
            visited.add(key)

        for key in self.catalog.items:
            visit(key, set())

    def test_every_quest_renders_offline_and_external_code_returns_same_record(self):
        with patch.object(requests, "get", side_effect=AssertionError("Quest lookup must stay offline")):
            self.assertEqual(len(self.catalog.items), 652)
            for key, row in self.catalog.items.items():
                with self.subTest(code=row["wiki_id"]):
                    result = self.catalog.reply(row["wiki_id"].lower())
                    self.assertEqual(result, self.catalog.detail(key))
                    self.assertTrue(result.startswith(row["wiki_id"] + ": "))
                    for heading in ("[임무 내용]", "[보상]"):
                        self.assertEqual(result.count(heading), 1)
                    self.assertEqual(result.count("[선행임무]"), bool(row["prereqs"]))
                    self.assertEqual(result.count("[후속임무]"), bool(self.catalog.after[key]))
                    self.assertEqual(quests.UNVERIFIED in result, bool(row["unverified"]))
                    self.assertEqual("[선행임무](검증중)" in result,
                                     bool(row["prereqs"] and row.get("prereqs_unverified")))
                    self.assertNotIn("등록 정보 없음", result)
                    self.assertLess(len(result), 4000)

    def test_priority_and_condition_reward_facts_match_saved_source_hashes(self):
        report = json.loads((ROOT / "data/quest_verification.json").read_text())
        self.assertEqual(report["priority"], ["verified", "quests.json", "unverified"])
        self.assertEqual(report["unresolved_prerequisite_ids"], [])
        for key, row in self.catalog.items.items():
            provenance = report["provenance"][key]
            for field in ("requirements", "rewards"):
                digest = hashlib.sha256(json.dumps(row[field], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                self.assertEqual(digest, provenance[field + "_sha256"], key)
        self.assertEqual(report["provenance"]["101"]["path"], "verified/quest_101.json")
        self.assertEqual(report["provenance"]["644"]["path"], "verified/quest_644.json")
        self.assertTrue(self.catalog.items["644"]["unverified"])
        self.assertEqual(self.catalog.by_code["f108"], "1114")
        self.assertNotIn("221114", self.catalog.items)
        self.assertEqual(self.catalog.reply("2609By1"), self.catalog.reply("By17"))

    def test_fleet_one_omitted_special_fleet_and_multiple_reward_groups_retained(self):
        self.assertNotIn("제1함대", self.catalog.reply("B100"))
        special = next(r for r in self.catalog.items.values() if r["requirements"].get("fleet_id") == 2)
        self.assertIn("제2함대", self.catalog.detail(str(special["game_id"])))
        reply = self.catalog.reply("F108")
        self.assertIn("선택1:", reply)
        self.assertIn("선택2:", reply)
        self.assertEqual(reply.count("(택1)"), 2)

    def test_periodic_special_dates_and_missing_detailed_conditions(self):
        self.assertIn("날짜 끝자리 3/7/0", self.catalog.reply("Bd4"))
        self.assertIn("날짜 끝자리 2/8", self.catalog.reply("Bd6"))
        self.assertIn("(계간)", self.catalog.reply("Bq6"))
        self.assertIn("(연간)", self.catalog.reply("Cy1"))
        b205 = self.catalog.reply("B205")
        self.assertEqual(b205.count("5-5/6-5/4-5 보스 S승 각 2회"), 1)
        self.assertIn("히에이 개2병", b205)
        self.assertIn("키리시마 개2병", b205)
        self.assertIn("시라츠유급/유구모급 2", b205)
        self.assertNotIn("편성안", b205)
        self.assertNotIn("중 1척", b205)
        self.assertIn("1-1/1-2/1-3/1-4 보스 S승 각 1회", self.catalog.reply("B210"))
        self.assertIn("후지나미 개2", self.catalog.reply("B207"))
        self.assertIn("시라유키 개2", self.catalog.reply("B208"))

    def test_wiki_prerequisites_and_reward_quantities(self):
        self.assertIn("[선행임무](검증중)\nB35", self.catalog.reply("B208"))
        self.assertIn("B208", self.catalog.reply("B35").split("[후속임무]")[1])
        self.assertIn("B5 + (Bd1 또는 Bd2)", self.catalog.reply("B48"))
        self.assertIn("B159 + Cy11", self.catalog.reply("B193"))
        self.assertNotIn("2307B1", self.catalog.reply("B193"))
        # A wiki omission alone must not delete previously registered edges.
        self.assertEqual(self.catalog.items["857"]["prereqs"], [228, 855])
        b205 = self.catalog.reply("B205")
        self.assertIn("35.6cm 연장포 개2 x2", b205)
        self.assertIn("신형포공병장자재 x6", b205)
        self.assertIn("전투상보 /", b205)
        self.assertNotIn(" x1 /", b205)
        self.assertIn("[선행임무]\nC77", b205)

    def test_all_quest_ship_ids_have_korean_display_names(self):
        ids = set()

        def visit(value):
            if isinstance(value, dict):
                if "ship_id" in value:
                    item = value["ship_id"]
                    ids.update(item if isinstance(item, list) else [item])
                for part in value.values():
                    visit(part)
            elif isinstance(value, list):
                for part in value:
                    visit(part)

        for row in self.catalog.items.values():
            visit(row["requirements"])
            visit(row["rewards"])
        remaining = {i: self.catalog.ship_name(i) for i in ids
                     if re.search(r"[一-龯ぁ-んァ-ン]", self.catalog.ship_name(i))}
        self.assertEqual(remaining, {})

    def test_usage_unknown_number_and_internal_id_are_not_misrouted(self):
        self.assertEqual(self.catalog.reply(""), quests.USAGE)
        self.assertIn("찾지 못했습니다", self.catalog.reply("B999999"))
        self.assertIn("찾지 못했습니다", self.catalog.reply("857"))

    def test_real_webhook_commands_reply_once_to_original_chat_without_get(self):
        with patch.object(requests, "get", side_effect=requests.RequestException("offline test")):
            import bot
        self.assertIn("!임무 [임무번호/임무명]", bot.COMMANDS["!도움말"])
        for query in ("b100", "증강 해상호위총대", "증강", "B98", "F108", ""):
            with self.subTest(query=query), patch.object(bot.requests, "get", side_effect=AssertionError("No GET")), \
                    patch.object(bot.requests, "post") as post:
                response = bot.app.test_client().post("/webhook", json={
                    "msg": "!임무 " + query, "room": None, "json": {"chat_id": "quest-room"},
                })
                self.assertEqual(response.status_code, 200)
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs["json"], {
                    "type": "text", "room": "quest-room", "data": self.catalog.reply(query),
                })
