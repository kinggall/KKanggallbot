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

    def test_by5_conditions_do_not_copy_by4(self):
        by4, by5 = self.catalog.reply('By4'), self.catalog.reply('By5')
        self.assertIn('4-1/4-2/4-3/4-4 보스 A승 이상 각 1회', by4)
        self.assertIn('하구로/아시가라/묘코/타카오/카미카제 중 2', by5)
        self.assertIn('7-2-2/7-3-2/4-2 보스 S승 각 2회', by5)
        self.assertNotIn('4-1/4-2/4-3/4-4', by5)
        self.assertIn('연료 1000/탄약 1000/강재 1000/보키 1000', by5)
        self.assertIn('B138 + B155', by5)
        self.assertIn('928', self.catalog.search_keys('하구로'))
        self.assertIn('4-5/5-3/5-5/6-4/6-5 보스 S승 각 1회', self.catalog.reply('B161'))

    def test_guide_source_exposes_missing_port_and_final_gauge(self):
        self.assertIn('1-6 도달 2회',self.catalog.reply('B191'))
        self.assertIn('5-4/5-5/5-6-3 보스 S승 각 2회',self.catalog.reply('B216'))

    def test_audited_victory_grades_and_flagships(self):
        for code in ('B93', 'B123', 'B142', 'B155', 'B211', 'By13', 'By18'):
            with self.subTest(code=code):
                reply = self.catalog.reply(code)
                self.assertIn('A승 이상', reply)
                self.assertNotIn('보스 S승', reply)
        self.assertIn('1-2 보스 B승 이상 1회', self.catalog.reply('B5'))
        self.assertNotIn('보스', self.catalog.reply('B4').split('[보상]')[0])
        self.assertIn(quests.UNVERIFIED, self.catalog.reply('B4'))
        for code in ('B213', 'B214'):
            self.assertIn('보스 S승 각 1회', self.catalog.reply(code))
        self.assertIn('하구로(기함)', self.catalog.reply('B155'))
        self.assertIn('(기함)', self.catalog.reply('B156').split('[보상]')[0])
        self.assertIn('야마시로 개2보(기함)', self.catalog.reply('By18'))
        self.assertIn('자유 0~3', self.catalog.reply('B214'))

    def test_audited_flagship_remodel_alternatives(self):
        for code, ship_ids in (('B141', {622, 623, 624}), ('By16', {1035, 1040})):
            row = self.catalog.items[self.catalog.by_code[code.casefold()]]
            flagship = next(c for c in row['requirements']['comp'] if c.get('position') == 1)
            self.assertEqual(set(flagship['ship_id']), ship_ids)
        self.assertIn('시구레 개2/시구레 개3 중 1', self.catalog.reply('B161'))
        self.assertIn('아케보노개/아케보노 개2 중 1', self.catalog.reply('By13'))

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

    def test_ship_aliases_search_conditions_and_titles_across_remodels(self):
        examples = {
            "베이": {"B170", "B187", "C68", "Cy6"},
            "뽀이": {"A78", "A84", "B103", "B112", "B197", "B199", "Cy12", "F78"},
            "오야시오": {"B174", "B184", "Cy7"},
        }
        for query, expected in examples.items():
            with self.subTest(query=query):
                reply = self.catalog.reply(query)
                codes = set(re.findall(r"\(([A-Za-z]+\d+)\)", reply))
                self.assertEqual(codes, expected)
        # C76 names Shigure in its title, while its structured candidate
        # list omits Shigure. The title must still make it searchable.
        self.assertIn("(C76)", self.catalog.reply("시구레"))
        self.assertIn("(C76)", self.catalog.reply("런구레"))

    def test_numbered_unit_short_names_and_long_names(self):
        expected = {
            "15구": {"B174", "B184", "Cy7"},
            "4수전": {"A78", "A84", "B112"},
            "1항전": {"A19", "B69", "B137", "B154", "F88"},
            "18전대": {"A51", "A89", "B43", "B120"},
        }
        for query, codes in expected.items():
            with self.subTest(query=query):
                actual = set(re.findall(r"\(([A-Za-z]+\d+)\)", self.catalog.reply(query)))
                self.assertEqual(actual, codes)
        for short, long in (("15구", "제15구축대"), ("4수전", "제4수뢰전대"),
                            ("1항전", "제1항공전대"), ("18전대", "第十八戦隊")):
            self.assertEqual(set(re.findall(r"\(([A-Za-z]+\d+)\)", self.catalog.reply(short))),
                             set(re.findall(r"\(([A-Za-z]+\d+)\)", self.catalog.reply(long))))
        self.assertEqual(quests.unit_mentions("제18구축대 / 第十八戦隊 / 제1항공전대"),
                         {(18, "구"), (18, "전대"), (1, "항전")})

    def test_commander_names_aliases_and_member_unions(self):
        self.assertEqual(len(self.catalog.search_keys("나구모")), 16)
        for name, commander in self.catalog.commanders.items():
            with self.subTest(commander=name):
                expected = set().union(*(set(self.catalog.search_keys(ship)) for ship in commander["ships"]))
                self.assertEqual(set(self.catalog.search_keys(name)), expected)
                for alias in commander["aliases"]:
                    self.assertEqual(set(self.catalog.search_keys(alias)), expected)
                self.assertTrue(all(not self.catalog.items[key].get("unavailable") for key in expected))
        self.assertEqual(self.catalog.search_keys("다몬마루"), self.catalog.search_keys("히류"))
        self.assertEqual(self.catalog.search_keys("시마키요 히데"), self.catalog.search_keys("키요히데"))
        self.assertEqual(self.catalog.search_keys("구리다 타케오"), self.catalog.search_keys("쿠리다"))
        self.assertIn("검색 결과 40개", self.catalog.reply("니시무라"))
        self.assertIn("앞의 30개만 표시합니다", self.catalog.reply("니시무라"))

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
            self.assertEqual(len(self.catalog.items), 664)
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
            if row.get('source_row'):
                digest = hashlib.sha256(json.dumps(row['source_row'], ensure_ascii=False).encode()).hexdigest()
                self.assertEqual(digest, row['source_sha256'])
                continue  # Wiki additions have separate, retained row evidence.
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

    def test_multistage_bosses_use_map_stage_labels(self):
        reply = self.catalog.reply("B206")
        self.assertIn("2-5/7-2-2/7-4/5-4 보스 S승 각 1회", reply)
        for code, label in (("B155", "7-3-1"), ("B157", "7-3-2"),
                            ("B190", "7-5-3")):
            self.assertIn(label, self.catalog.reply(code))
        self.assertIn("7-4 O지점", self.catalog.reply("B175"))

    def test_named_ship_selection_counts(self):
        b157 = self.catalog.reply("B157")
        self.assertIn("유구모 개2/마키구모 개2/카자구모 개2/아키구모 개2 + 자유 0~2", b157)
        self.assertNotIn("아키구모 개2 4", b157)
        self.assertIn("아키시모/키요시모 중 1", self.catalog.reply("B206"))
        self.assertIn("후지나미 개2(기함)", self.catalog.reply("B207"))

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

    def test_corrected_names_removed_expired_quest_and_usage(self):
        self.assertIn("철저하나노데스!", self.catalog.reply("B45"))
        self.assertEqual(self.catalog.reply("진츠"), self.catalog.reply("A14"))
        self.assertIn("241009", self.catalog.items)
        archived = self.catalog.reply("2404 B4")
        self.assertIn("(기간한정/종료)", archived)
        self.assertIn("[선행임무]\n2404 B2", archived)
        self.assertNotIn("2604 B5", archived)
        self.assertIn("선택1: 보상 정보 미등록", archived)
        self.assertNotIn("선택1:  (택1)", archived)
        self.assertIn("찾지 못했습니다", self.catalog.reply("함대, 남방전선으로"))
        self.assertIn("센다이/진츠/나카", self.catalog.reply("A14"))
        self.assertNotIn("나차", self.catalog.reply("A14"))
        self.assertEqual(self.catalog.reply("ㅇㅇㅇ"), "'ㅇㅇㅇ' 임무를 찾지 못했습니다.\n"
                         "사용법: !임무 [번호/키워드]\n예: !임무 B44 / 반격 / 6구 / 찐빵")
        with patch.object(requests, "get", side_effect=requests.RequestException("offline test")):
            import bot
        self.assertEqual(bot.SHIP_TRANSLATIONS["那珂"], "나카")
        improvement = bot.build_improvement_reply("나카")
        self.assertIn("나카 개수 가능 장비", improvement)
        self.assertNotIn("나차", improvement)

    def test_expired_quests_only_match_exact_codes(self):
        for key, row in self.catalog.items.items():
            if not row.get("unavailable"):
                continue
            with self.subTest(code=row["wiki_id"]):
                self.assertEqual(self.catalog.reply(row["wiki_id"].lower()), self.catalog.detail(key))
                reply = self.catalog.reply(row["name_ko"])
                self.assertNotIn(f"({row['wiki_id']})", reply)
                self.assertNotEqual(reply, self.catalog.detail(key))

    def test_real_webhook_commands_reply_once_to_original_chat_without_get(self):
        with patch.object(requests, "get", side_effect=requests.RequestException("offline test")):
            import bot
        self.assertIn("!임무 [번호/키워드]", bot.COMMANDS["!도움말"])
        for query in ("b100", "증강 해상호위총대", "증강", "B98", "F108", "나구모", "기무라", "다몬마루", ""):
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
