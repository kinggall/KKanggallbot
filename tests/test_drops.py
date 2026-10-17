"""Drop regressions: run python -m unittest discover -s tests -v."""
import atexit
import csv
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_cache = tempfile.TemporaryDirectory()
atexit.register(_cache.cleanup)
with patch.dict(os.environ, {"XDG_CACHE_HOME": _cache.name, "LOCALAPPDATA": _cache.name}), \
        patch("requests.get", side_effect=requests.RequestException("offline import")):
    bot = importlib.import_module("bot")

# Condensed actual structure: the first table has node tooltips; the second is
# the map summary. Permanent notes must never become limited locations.
WIKI = '''
<h3>現在継続中の期間限定ドロップ艦（2026-09-10メンテ時点）</h3>
<table><tr><th>艦娘名</th><th>対象</th></tr><tr><td>艦娘</td><td>
<a data-tooltip-content="2-3-N(ボス)&lt;br&gt;※5-5-S(ボス)で常設ドロップあり">阿賀野</a>
<a data-tooltip-content="7-5-M&lt;br&gt;※7-5-K(第1ボス)、7-5-T(第3ボス)にて恒常ドロップあり">Houston</a>
<a data-tooltip-content="1-6-B,D,F,J">Langley</a>
<a data-tooltip-content="2ｰ5ｰO(ボス)&lt;br&gt;※6ｰ5ｰM(ボス)で恒常ドロップあり">海風</a>
</td></tr></table>
<table><tr><th>海域</th><th>エリア</th><th>ドロップ対象</th></tr>
<tr><th rowspan="2">南西</th><td>2-3</td><td><a>阿賀野</a></td></tr>
<tr><td>7-5</td><td><a>Houston</a></td></tr></table>
<h2>過去のイベント</h2><table><tr><td>not current</td></tr></table>
'''


def entry(name="阿賀野", node="N", rarity=1, pct=1.0, **extra):
    return dict(id=137, name=name, name_en=name, node=node, rarity=rarity,
                drops=10, total=1000, pct=pct, **extra)


class DropTests(unittest.TestCase):
    def setUp(self):
        self.current = dict(schema_version=2, updated_at="test",
                            maps=bot.parse_current_limited_drops(WIKI),
                            locations=bot.parse_limited_drop_locations(WIKI))
        self.state = patch.object(bot, "CURRENT_LIMITED_DROPS", self.current)
        self.state.start()
        self.addCleanup(self.state.stop)
        self.names = patch.object(bot, "DROP_SHIP_NAMES", {})
        self.names.start()
        self.addCleanup(self.names.stop)

    def test_summary_skips_first_ship_table_and_handles_rowspan(self):
        self.assertEqual(self.current["maps"], {"2-3": ["阿賀野"], "7-5": ["Houston"]})

    def test_exact_locations_and_permanent_notes(self):
        self.assertEqual(bot.drop_entry_status(entry(), "2-3"), "limited")
        self.assertEqual(bot.drop_entry_status(entry(node="S"), "5-5"), "permanent")
        self.assertEqual(bot.drop_entry_status(entry("Houston", "T", 2), "7-5"), "permanent")
        self.assertEqual(bot.drop_entry_status(entry("Houston", "M", 2), "7-5"), "limited")

    def test_unicode_hyphens_and_shared_map_nodes(self):
        records = self.current["locations"]
        self.assertEqual({x["node"] for x in records if x["name"] == "Langley"}, {"B", "D", "F", "J"})
        self.assertEqual(bot.drop_entry_status(entry("海風", "O"), "2-5"), "limited")
        self.assertEqual(bot.drop_entry_status(entry("海風", "M"), "6-5"), "permanent")

    def test_summary_without_node_is_not_asserted_limited(self):
        self.current["maps"]["1-1"] = ["瑞穂"]
        self.assertEqual(bot.drop_entry_status(entry("瑞穂", "C"), "1-1"), "unverified")

    def test_new_event_after_old_summary_is_included(self):
        recent = '''<h2>【Halloween】期間限定邂逅 (2026/10/14～継続中)</h2>
        <table><tr><th>海域</th><th>エリア</th><th>ドロップ対象</th></tr>
        <tr><th>鎮守府</th><td>1-1-C(ボス)</td><td><a>早波</a>, <a>浜波</a></td></tr></table>'''
        maps = bot.parse_current_limited_drops(WIKI + recent)
        locations = bot.parse_limited_drop_locations(WIKI + recent)
        self.assertEqual(maps["1-1"], ["早波", "浜波"])
        self.assertTrue(any(x["name"] == "早波" and x["node"] == "C" for x in locations))

    def test_api_variant_name_matches_wiki_by_game_id(self):
        self.current["locations"].append({"map": "1-4", "node": "L", "name": "宗谷", "limited": True})
        with patch.object(bot, "DROP_SHIP_NAMES", {699: {bot.normalize_ship_name("宗谷")}}):
            souya = dict(entry("宗谷(AGS)", "L", 2), id=699)
            self.assertEqual(bot.drop_entry_status(souya, "1-4"), "limited")

    def test_final_boss_and_all_incoming_edges(self):
        for map_name, nodes in bot.BOSS_NODES_BY_STAGE.items():
            with self.subTest(map=map_name):
                route = {str(i): ["X", node, 5, 5] for i, node in enumerate(nodes, 1)}
                route["90"] = ["Y", nodes[-1], 5, 5]
                with patch.object(bot, "get_tsunkit_json", return_value={"result": {"route": route}}):
                    self.assertEqual(bot.get_map_boss_edges(map_name), [str(len(nodes)), "90"])
                    self.assertEqual(bot.get_map_boss_edges(map_name, 1), ["1"])
                    with self.assertRaises(ValueError):
                        bot.get_map_boss_edges(map_name, len(nodes) + 1)

    def test_unknown_multi_boss_is_not_mixed(self):
        route = {"1": ["A", "B", 5], "2": ["C", "D", 5]}
        with patch.object(bot, "get_tsunkit_json", return_value={"result": {"route": route}}):
            with self.assertRaises(ValueError):
                bot.get_map_boss_edges("9-1")

    def test_selected_boss_request_and_annotation(self):
        payload = {"result": {"entries": [entry(node="ignored")]}}
        with patch.object(bot, "get_map_boss_groups", return_value=[("K", ["11"]), ("T", ["24", "25"])]), \
                patch.object(bot, "get_tsunkit_json", return_value=payload) as api:
            result = bot.get_boss_drops("7-5")
            self.assertEqual(api.call_args.args[0], "/maps/7-5/edges/24,25/drops")
            self.assertEqual(api.call_args.args[1]["ranks"], "SA")
            self.assertEqual({x["node"] for x in result}, {"T"})
            self.assertEqual(result[0]["boss_stage"], 2)

    def test_unconfirmed_exclusive_omitted_and_permanent_exclusive_kept(self):
        old = entry("Ended", "T", 2)
        permanent = entry("Houston", "T", 2)
        result = bot.filter_rare_and_limited_drops([old, permanent], "7-5")
        self.assertEqual([x["name"] for x in result], ["Houston"])
        self.assertFalse(result[0]["limited"])

    def test_all_rare_rows_and_no_drop_excluded(self):
        values = [dict(entry(pct=float(i)), drops=i * 10) for i in range(9)]
        values += [{"id": 0, "rarity": 1}, entry("Common", rarity=0)]
        result = bot.filter_rare_and_limited_drops(values, "5-5")
        self.assertEqual(len(result), 9)
        self.assertEqual([x["pct"] for x in result], list(reversed(range(9))))

    def test_positive_tiny_probability_is_not_printed_as_zero(self):
        sample = dict(entry(pct=0.0), drops=12, total=245181)
        self.assertEqual(bot.format_drop_rate(sample), "<0.01%")

    def test_ship_recommendations_include_both_statuses(self):
        values = [entry(map_name=f"{i}-1", limited=False, drop_status="permanent") for i in range(1, 7)]
        values += [entry(map_name="2-3", limited=True, drop_status="limited")]
        values[-1].update(drops=1, pct=0.1)
        text = bot.format_ship_drops("아가노", [], values)
        self.assertEqual(sum(line.startswith("· ") for line in text.splitlines()), 5)
        self.assertIn("2-3-N", text)
        self.assertEqual(text.count("(기간한정)"), 1)

    def test_incompatible_samples_not_summed(self):
        a = entry(map_name="2-3", limited=False, drop_status="permanent")
        b = dict(a, total=2000)
        with self.assertRaises(ValueError):
            bot.format_ship_drops("name", [], [a, b])

    def test_alias_and_remodel_resolve_identical_drop_rows(self):
        ships = [{"艦船ID": "1", "艦名": "夕立", "改装後": "夕立改", "改装段階": "0"},
                 {"艦船ID": "2", "艦名": "夕立改", "改装前": "夕立", "改装段階": "1"}]
        with patch.multiple(bot, SHIPS=ships, SHIP_TRANSLATIONS={"夕立": "유다치"},
                            SHIP_ALIASES={"夕立": ["뽀이", "유다치"]}), \
                patch.object(bot, "SHIP_GRAPH", {0: {1}, 1: {0}}), \
                patch.object(bot, "tsunkit_map_names", return_value=["1-1"]), \
                patch.object(bot, "get_boss_drops", return_value=[dict(entry(node="C"), id=1)]):
            self.assertEqual(bot.find_ship_boss_drops("유다치"), bot.find_ship_boss_drops("뽀이"))

    def test_all_repository_aliases_resolve_to_their_ship_family(self):
        root = Path(__file__).resolve().parents[1]
        with (root / "ships.csv").open(encoding="cp932", newline="") as file:
            ships = [row for row in csv.DictReader(file) if int(row["艦船ID"]) <= 1500]
        aliases = json.loads((root / "data/ship_aliases.json").read_text(encoding="utf-8"))
        with patch.multiple(bot, SHIPS=ships, SHIP_TRANSLATIONS={}, SHIP_ALIASES=aliases):
            with patch.object(bot, "SHIP_GRAPH", bot.build_ship_graph()):
                for canonical, registered in aliases.items():
                    expected = {ship["艦船ID"] for ship, _ in bot.search_ships(canonical)}
                    self.assertTrue(expected, canonical)
                    for alias in registered:
                        actual = {ship["艦船ID"] for ship, _ in bot.search_ships(alias)}
                        self.assertEqual(actual, expected, f"{canonical}: {alias}")
                i503 = {ship["艦名"] for ship, _ in bot.search_ships("I-503")}
                i504 = {ship["艦名"] for ship, _ in bot.search_ships("I-504")}
                self.assertIn("C.Cappellini", i503)
                self.assertNotIn("Luigi Torelli", i503)
                self.assertIn("Luigi Torelli", i504)
                self.assertNotIn("C.Cappellini", i504)

    def test_12_hour_cache_hit_expiry_and_reload(self):
        payload = {"result": {"ok": True}}
        cache = {"/maps/test?": {"saved_at": 100, "payload": payload}}
        response = Mock()
        response.json.return_value = payload
        with patch.object(bot, "TSUNKIT_CACHE", cache), patch.object(bot.time, "time", return_value=101), \
                patch.object(bot.requests, "get", return_value=response) as http, \
                patch.object(bot, "TSUNKIT_CACHE_FILE", Path(_cache.name) / "cache.json"):
            self.assertEqual(bot.get_tsunkit_json("/maps/test"), payload)
            http.assert_not_called()
            with patch.object(bot.time, "time", return_value=100 + 12 * 3600 + 1):
                bot.get_tsunkit_json("/maps/test")
            http.assert_called_once()
            self.assertEqual(bot.load_tsunkit_cache(), cache)

    def test_refresh_failure_preserves_previous_file_and_state(self):
        path = Path(_cache.name) / "limited.json"
        path.write_text(json.dumps(self.current), encoding="utf-8")
        response = Mock(text="<html>unexpected</html>")
        old = path.read_bytes()
        with patch.object(bot, "LIMITED_DROPS_CACHE_FILE", path), \
                patch.object(bot.requests, "get", return_value=response):
            with self.assertRaises(ValueError):
                bot.refresh_current_limited_drops()
        self.assertEqual(path.read_bytes(), old)

    def test_legacy_map_only_cache_requires_refresh(self):
        path = Path(_cache.name) / "legacy.json"
        path.write_text('{"updated_at":"old","maps":{"7-5":["Houston"]}}', encoding="utf-8")
        with patch.object(bot, "LIMITED_DROPS_CACHE_FILE", path):
            self.assertIsNone(bot.load_limited_drops_cache()["updated_at"])

    def test_webhook_acknowledges_before_slow_search(self):
        with patch.object(bot.DROP_COMMAND_EXECUTOR, "submit") as submit:
            response = bot.app.test_client().post("/webhook", json={"msg": "!드랍 뽀이", "json": {"chat_id": "123"}})
            self.assertEqual(response.status_code, 200)
            submit.assert_called_once_with(bot.send_drop_reply, "!드랍 뽀이", "123")

    def test_iris_reply_keeps_chat_id_and_limited_marker(self):
        with patch.object(bot, "build_drop_reply", return_value="· 아가노 1.99% (기간한정)"), \
                patch.object(bot.requests, "post") as send:
            bot.send_drop_reply("!드랍 아가노", "123")
            self.assertEqual(send.call_args.kwargs["json"]["room"], "123")
            self.assertIn("(기간한정)", send.call_args.kwargs["json"]["data"])


if __name__ == "__main__":
    unittest.main()
