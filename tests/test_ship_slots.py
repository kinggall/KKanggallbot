"""Offline slot regressions, including every remodel form in ships.csv."""
import atexit
import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_cache = tempfile.TemporaryDirectory()
atexit.register(_cache.cleanup)
with patch.dict(os.environ, {"XDG_CACHE_HOME": _cache.name, "LOCALAPPDATA": _cache.name}), \
        patch("requests.get", side_effect=requests.RequestException("offline import")):
    bot = importlib.import_module("bot")

from scripts.build_ship_aircraft_rules import build_rules


class ShipSlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "ships.csv").open(encoding="cp932", newline="") as file:
            cls.ships = [row for row in csv.DictReader(file) if int(row["艦船ID"]) <= 1500]
        cls.by_id = {row["艦船ID"]: row for row in cls.ships}
        cls.rules = json.loads((ROOT / "data/ship_aircraft_rules.json").read_text(encoding="utf-8"))
        cls.aliases = json.loads((ROOT / "data/ship_aliases.json").read_text(encoding="utf-8"))

    def setUp(self):
        state = patch.multiple(bot, SHIPS=self.ships, SHIP_TRANSLATIONS={},
                               SHIP_ALIASES=self.aliases, SHIP_AIRCRAFT_RULES=self.rules["ships"])
        state.start()
        self.addCleanup(state.stop)
        graph = patch.object(bot, "SHIP_GRAPH", bot.build_ship_graph())
        graph.start()
        self.addCleanup(graph.stop)

    def test_every_csv_form_is_verified_and_positive_slots_are_equipable(self):
        self.assertEqual(set(self.by_id), set(self.rules["ships"]))
        self.assertEqual(len(self.ships), self.rules["verified_csv_forms"])
        self.assertEqual(hashlib.sha256((ROOT / "ships.csv").read_bytes()).hexdigest(),
                         self.rules["csv_sha256"])
        counts = {"positive": 0, "zero_allowed": 0, "zero_disallowed": 0}
        for ship in self.ships:
            with self.subTest(ship=ship["艦名"], ship_id=ship["艦船ID"]):
                values = [ship[f"搭載機数{i}"] for i in range(1, int(ship["スロット数"]) + 1)]
                status = bot.ship_aircraft_status(ship)
                self.assertIsNotNone(status)
                text = bot.ship_slot_text(ship)
                if any(int(value) > 0 for value in values):
                    counts["positive"] += 1
                    self.assertIs(status, True)
                    self.assertIn(" / ".join(values), text)
                    self.assertNotIn(bot.NO_AIRCRAFT_MESSAGE, text)
                elif status:
                    counts["zero_allowed"] += 1
                    self.assertIn(" / ".join(values), text)
                    self.assertIn("장착 가능 · 탑재량 0", text)
                else:
                    counts["zero_disallowed"] += 1
                    self.assertIn(bot.NO_AIRCRAFT_MESSAGE, text)
                self.assertNotIn("슬롯1", text)
        self.assertEqual(counts, {"positive": 401, "zero_allowed": 20, "zero_disallowed": 445})

    def test_kaga_all_five_forms_and_capacity_only_format(self):
        self.assertEqual(bot.build_ship_slots_reply("카가"),
                         "[미개장]\n18 / 18 / 45 / 12\n\n"
                         "[개1]\n20 / 20 / 46 / 12\n\n"
                         "[개2]\n20 / 20 / 44 / 12 / 3\n\n"
                         "[개2무]\n18 / 18 / 40 / 8 / 2\n\n"
                         "[개2호]\n16 / 16 / 18 / 8 / 6")

    def test_oyodo_preserves_internal_and_trailing_zero_slots(self):
        self.assertEqual(bot.build_ship_slots_reply("오요도"),
                         "[미개장]\n0 / 6 / 6\n\n[개1]\n0 / 6 / 6 / 0")

    def test_inazuma_collapses_all_unavailable_forms_to_one_message(self):
        self.assertEqual(bot.build_ship_slots_reply("이나즈마"), bot.NO_AIRCRAFT_MESSAGE)

    def test_sam_alias_keeps_unavailable_base_and_available_mkii(self):
        text = bot.build_ship_slots_reply("샘")
        self.assertEqual(text.count(bot.NO_AIRCRAFT_MESSAGE), 2)
        self.assertIn("[Mk.II]\n1 / 1 / 1", text)
        self.assertEqual(text, bot.build_ship_slots_reply("Samuel B.Roberts"))

    def test_zero_capacity_exceptions_are_not_treated_as_disallowed(self):
        for ship_id in ("51", "115", "141", "597", "162", "182", "944", "953"):
            with self.subTest(ship_id=ship_id):
                self.assertIs(bot.ship_aircraft_status(self.by_id[ship_id]), True)
                self.assertNotIn(bot.NO_AIRCRAFT_MESSAGE, bot.ship_slot_text(self.by_id[ship_id]))
        # Yuubari's base/Kai can equip recon planes, but Kai Ni variants cannot.
        for ship_id in ("622", "623", "624"):
            self.assertIs(bot.ship_aircraft_status(self.by_id[ship_id]), False)
        # Submarine aircraft carriers and pure submarines must not share one rule.
        self.assertIs(bot.ship_aircraft_status(self.by_id["127"]), False)  # I-58 before remodel
        self.assertIs(bot.ship_aircraft_status(self.by_id["399"]), True)  # I-58 Kai
        self.assertIn("[개1]\n1 / 1", bot.build_ship_slots_reply("伊58"))
        self.assertIs(bot.ship_aircraft_status(self.by_id["126"]), False)  # I-168
        self.assertIs(bot.ship_aircraft_status(self.by_id["1071"]), True)  # Kitakami Kai San
        self.assertIs(bot.ship_aircraft_status(self.by_id["119"]), False)  # Kitakami Kai Ni

    def test_missing_rule_does_not_claim_aircraft_are_unequipable(self):
        with patch.object(bot, "SHIP_AIRCRAFT_RULES", {}):
            text = bot.build_ship_slots_reply("이나즈마")
        self.assertNotIn(bot.NO_AIRCRAFT_MESSAGE, text)
        self.assertIn("항공기 장착 가능 여부 미확인", text)

    def test_webhook_routes_slots_and_preserves_reply_room(self):
        with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as send:
            response = bot.app.test_client().post("/webhook", json={
                "msg": "!슬롯 이나즈마", "room": None, "json": {"chat_id": "test-room"}
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_args.kwargs["json"]["room"], "test-room")
        self.assertEqual(send.call_args.kwargs["json"]["data"], bot.NO_AIRCRAFT_MESSAGE)
        self.assertEqual(bot.build_ship_slots_reply(""), "사용법: !슬롯 함선명")
        self.assertIn("찾지 못했습니다", bot.build_ship_slots_reply("존재하지않는함선"))

    def test_master_ship_override_replaces_type_and_handles_item_restrictions(self):
        master = {
            "api_mst_ship": [{"api_id": 1, "api_stype": 3, "api_slot_num": 2, "api_maxeq": [0, 0]}],
            "api_mst_stype": [{"api_id": 3, "api_equip_type": {"10": 1, "11": 1, "35": 1}}],
            "api_mst_equip_ship": {"1": {"api_equip_type": {"25": [69], "10": [], "35": None}}},
        }
        row = {"艦船ID": "1", "艦名": "test", "スロット数": "2", "搭載機数1": "0", "搭載機数2": "0"}
        self.assertEqual(build_rules(master, [row]), {"1": [25]})
        master["api_mst_equip_ship"] = {}
        self.assertEqual(build_rules(master, [row]), {"1": [10, 11]})
        row["搭載機数1"] = "1"
        with self.assertRaises(ValueError):
            build_rules(master, [row])


if __name__ == "__main__":
    unittest.main()
