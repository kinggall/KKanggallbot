"""Offline equipment recipes, ported from SkywalkerJi/kc-development-tools.

SPDX-License-Identifier: GPL-3.0-only
Modified 2026-10-18: Python port, Korean presentation and equipment alias lookup.
Upstream revision and preserved licensing: THIRD_PARTY_NOTICES.md.
"""
from dataclasses import dataclass
from functools import cmp_to_key, lru_cache
import json
from pathlib import Path

import equipment_lookup


SHIP_TYPES = dict(zip(
    ("NULL", "DE", "DD", "CL", "CLT", "CA", "CAV", "CVL", "FBB", "BB", "BBV", "CV",
     "超弩級戦艦", "SS", "SSV", "敌AO", "AV", "LHA", "CVB", "AR", "AS", "CT", "AO"),
    range(23),
))
POOL_LABELS = {
    "炮战系-意": "전함계-리토리오/로마/차라/폴라",
    "炮战系-厌战英勇": "전함계-워스파이트/발리언트",
    "炮战系-纳尔逊罗德尼": "전함계-넬슨/로드니",
    "炮战系-比叡改二": "전함계-히에이 개2",
    "炮战系-金刚级": "전함계-콩고형",
    "炮战系-内华达": "전함계-네바다",
    "炮战系-黎塞留级": "전함계-리슐리외형",
    "炮战系-大和级(大和改二重除外)": "전함계-야마토형(야마토 개2중 제외)",
    "炮战系-北安普敦": "전함계-노샘프턴",
    "炮战系-其它": "전함계",
    "水雷系-阿贺野级": "수뢰계-아가노형",
    "水雷系-川内改二": "수뢰계-센다이 개2",
    "水雷系-神通改二": "수뢰계-진츠 개2",
    "水雷系-海伦娜": "수뢰계-헬레나",
    "水雷系-大淀": "수뢰계-오요도",
    "水雷系-意驱": "수뢰계-이탈리아 구축함",
    "水雷系-德驱": "수뢰계-독일 구축함",
    "水雷系-秋月级": "수뢰계-아키즈키형",
    "水雷系-神风级": "수뢰계-카미카제형",
    "水雷系-睦月级": "수뢰계-무츠키형",
    "水雷系-吹白雪改二": "수뢰계-후부키 개2/시라유키 개2",
    "水雷系-吹雪级": "수뢰계-후부키형",
    "水雷系-天津风": "수뢰계-아마츠카제",
    "水雷系-其它驱逐舰": "수뢰계-구축함",
    "水雷系-海防舰": "수뢰계-해방함",
    "水雷系-灯泡宗谷、南极宗谷": "수뢰계-소야(등대보급선/남극관측선)",
    "水雷系-山汐丸": "수뢰계-야마시오마루",
    "水雷系-32驱改二": "수뢰계-제32구축대 개2",
    "水雷系-其它": "수뢰계",
    "空母系-日向改": "항모계-휴가 개",
    "空母系-伊势改": "항모계-이세 개",
    "空母系-方舟": "항모계-아크 로열",
    "空母系-萨拉、大黄蜂": "항모계-사라토가/호넷",
    "空母系-列克星敦": "항모계-렉싱턴",
    "空母系-二航战": "항모계-제2항공전대(소류/히류)",
    "空母系-大凤": "항모계-타이호",
    "空母系-大凤改": "항모계-타이호 개",
    "空母系-五航改二(甲)": "항모계-쇼카쿠/즈이카쿠 개2(갑 포함)",
    "空母系-塔斯特": "항모계-코망단 테스트",
    "空母系-陆军、特务宗谷": "항모계-육군 함선/소야(특무함)",
    "空母系-齐柏林": "항모계-그라프 체펠린",
    "空母系-其它": "항모계",
    "潜水系-Scamp、Salmon": "잠수계-스캠프/새먼",
    "潜水系-潜水母舰": "잠수계-잠수모함",
    "潜水系-其它": "잠수계",
}
# Offer the four unrestricted base families as the general fallback, matching
# the website's "other" categories (not narrower destroyer/AS-only subpools).
GENERAL_POOLS = frozenset((
    "炮战系-其它", "水雷系-其它", "空母系-其它", "潜水系-其它",
))


@dataclass(frozen=True)
class Recipe:
    pool_name: str
    pool_id: int
    resources: tuple
    probability: int
    failure: int

    @property
    def total(self):
        return sum(self.resources)


def compare_recipes(a, b):
    """Match upstream display sort, including its resource difference <= 1 tie."""
    if a.probability != b.probability:
        return b.probability - a.probability
    if abs(a.total - b.total) > 1:
        return a.total - b.total
    return b.failure - a.failure


def remodel_chains(ships):
    """Preserve original order, merging-path ownership and cycle starting points."""
    players = {s["api_id"]: s for s in ships if s["api_id"] < 1500}
    after = {i: int(s.get("api_aftershipid", 0)) for i, s in players.items()}
    successors = set(after.values()) - {0}
    processed, chains = set(), []

    def walk(start, allowed=None):
        chain, current = [], start
        while current in players and current not in processed and (allowed is None or current in allowed):
            chain.append(current)
            processed.add(current)
            current = after[current]
        return chain

    for ship_id in players:
        if ship_id not in successors and ship_id not in processed:
            chains.append(walk(ship_id))
    while len(processed) < len(players):
        current = next(i for i in players if i not in processed)
        cycle = []
        while current in players and current not in cycle:
            cycle.append(current)
            current = after[current]
        if current not in cycle:
            raise ValueError("개발 데이터의 함선 개장 고리를 확인할 수 없습니다.")
        chains.append(walk(max(cycle), set(cycle)))
    return {ship_id: chain for chain in chains for ship_id in chain}


def derive_resources(pool_type, broken, item_id):
    base = [240, 260, 10, 250] if item_id == 168 else [10, 10, 10, 10]
    base = [max(value, cost * 10) for value, cost in zip(base, broken)]
    if pool_type == 1:
        base[3] = max(base[3], max(base[:3]) + 1)
    elif pool_type == 2:
        base[1] = max(base[1], base[0] + 1, base[2] + 1, base[3])
    elif not (base[0] >= max(base[1], base[3]) or base[2] >= max(base[1], base[3])):
        oil, steel = base[:], base[:]
        oil[0] = max(oil[0], oil[1], oil[3])
        steel[2] = max(steel[2], steel[1], steel[3])
        return [tuple(oil), tuple(steel)]
    return [tuple(base)]


class DevelopmentCatalog:
    def __init__(self, root):
        folder = root / "data/development"
        read = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
        master, ctypes = read("start2.json"), read("ctype.json")
        self.equipment = {e["api_id"]: e["api_broken"] for e in master["api_mst_slotitem"]}
        ships = {s["api_id"]: s for s in master["api_mst_ship"]}
        chains = remodel_chains(master["api_mst_ship"])

        def resolve_names(names):
            result = []
            for name in names:
                hit = next((i for i, s in ships.items() if s["api_name"] == name), None)
                if hit is None:
                    return result
                chain = chains.get(hit, [])
                if hit in chain:
                    result.extend(chain[chain.index(hit):])
            return result

        self.pools, self.selectable = [], []
        for raw in read("DevelopmentPool.json"):
            ids = list(raw.get("舰ID", []))
            stypes = {SHIP_TYPES[t] for t in raw.get("舰种", [])}
            classes = set()
            for value in raw.get("舰型", []):
                if str(value).isdigit():
                    classes.add(int(value))
                else:
                    classes.add(next(int(k) for k, v in ctypes.items() if v == value))
            # Duplicates are intentional in upstream expansion.
            ids.extend(i for i in sorted(ships) if i < 1500 and ships[i]["api_stype"] in stypes)
            ids.extend(i for i in sorted(ships) if i < 1500 and ships[i]["api_ctype"] in classes)
            ids.extend(resolve_names(raw.get("舰名", [])))
            for excluded in raw.get("不包含舰ID", []):
                if excluded in ids:
                    ids.remove(excluded)
            pool = dict(name=raw["开发池名称"], kind=raw["开发池ID"], ids=ids,
                        members=frozenset(ids), rates={int(k): v for k, v in raw["出货率"].items()})
            self.pools.append(pool)
            if raw["开发池ID"] >= 0 and not raw.get("最低资源") and pool["name"] not in self.selectable:
                self.selectable.append(pool["name"])
        missing_labels = set(self.selectable) - POOL_LABELS.keys()
        if missing_labels:
            raise ValueError(f"개발 비서함 번역 누락: {missing_labels}")

    @lru_cache(maxsize=1024)
    def recipes(self, item_id):
        if item_id not in self.equipment:
            return ()
        results = []
        for name in self.selectable:
            for kind in (1, 2, 3):
                base = next((p for p in self.pools if p["name"] == name and p["kind"] == kind), None)
                if base is None:
                    continue
                rates = {}
                for pool in self.pools:
                    if abs(pool["kind"]) != kind or not base["members"] <= pool["members"]:
                        continue
                    for equip_id, rate in pool["rates"].items():
                        rates[equip_id] = rates.get(equip_id, 0) + (rate if pool["kind"] > 0 or item_id == 168 else 0)
                probability = rates.get(item_id, 0)
                if probability <= 0:
                    continue
                for resources in derive_resources(kind, self.equipment[item_id], item_id):
                    other = sum(rate for equip_id, rate in rates.items()
                                if equip_id != item_id and equip_id in self.equipment
                                and all(r >= cost * 10 for r, cost in zip(resources, self.equipment[equip_id])))
                    failure = 100 - probability - other
                    if probability + failure > 100:
                        continue
                    results.append(Recipe(name, kind, resources, probability, failure))
        return tuple(sorted(results, key=cmp_to_key(compare_recipes)))

    def reply(self, query, equipment):
        query = query.strip()
        if not query:
            return "사용법: !개발 장비명 / !개발 #장비번호"
        matches = equipment.search(query)
        if len(matches) != 1:
            # Keep equipment lookup's aliases, candidate limits and ID behavior.
            return equipment.reply(query).replace("!장비", "!개발")
        item_id = matches[0]
        recipes = self.recipes(item_id)
        name = equipment.items[item_id]["name"]
        if not recipes:
            return f"{name}\n· 개발불가"
        best = recipes[0]
        selected = [("최적", best)]
        if best.pool_name not in GENERAL_POOLS:
            general = next((r for r in recipes if r.pool_name in GENERAL_POOLS), None)
            if general is not None:
                if (best.resources, best.probability, best.failure) == (general.resources, general.probability, general.failure):
                    selected = [("최적", general)]
                else:
                    selected.append(("범용", general))
        blocks = []
        for title, recipe in selected:
            blocks.append(f"[{title}]\n· 비서함 : {POOL_LABELS[recipe.pool_name]}\n"
                          f"· {' / '.join(map(str, recipe.resources))}\n"
                          f"· 개발 확률 {recipe.probability:g}% / 실패율 {recipe.failure:g}%")
        return "\n".join(blocks)


@lru_cache(maxsize=1)
def catalog():
    return DevelopmentCatalog(Path(__file__).parent)


def build_reply(query):
    return catalog().reply(query, equipment_lookup.catalog())
