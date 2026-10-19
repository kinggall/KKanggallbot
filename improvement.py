"""Offline EO equipment improvement costs and conversion routes.

SPDX-License-Identifier: GPL-3.0-only
Data provenance and level semantics: IMPROVEMENT_DATA.md.
"""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

import equipment_lookup

DAY_ORDER = (1, 2, 3, 4, 5, 6, 0)
DAYS = {0: "일", 1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토"}
CONSUMABLES = {
    2: "고속건조재",
    57: "훈장", 70: "숙련탑승원", 71: "네식 엔진", 75: "신형포공병장자재",
    77: "신형항공병장자재", 78: "전투상보", 91: "긴급수리자재", 92: "신형분진장비개발자재",
    94: "신형병장자재", 95: "잠수함보급물자", 100: "해외함 최신기술", 104: "공창자원",
}


def merged_materials(items):
    result = defaultdict(int)
    for item in items:
        result[item["id"]] += item["eq_count"]
    return tuple(sorted((item_id, count) for item_id, count in result.items() if count))


def cost_at(costs, target):
    """EO levels are target stars: 1..6=p1, 7..10=p2, 255=conversion.

    Extra material lists ADD to the base cost at the listed target levels.
    Caller-facing intervals use the CURRENT stars, i.e. target minus one.
    """
    base = costs.get("conv") if target == 255 else costs["p1" if target <= 6 else "p2"]
    if base is None:
        return None
    result = deepcopy(base)
    for extra in costs.get("extra", []):
        if target not in extra["levels"]:
            continue
        for key in ("equips", "consumable"):
            result.setdefault(key, []).extend(extra.get(key, []))
    return (result["devmats"], result["devmats_sli"], result["screws"], result["screws_sli"],
            merged_materials(result.get("equips", [])), merged_materials(result.get("consumable", [])))


def star_ranges(costs):
    ranges = []
    for current in range(10):
        value = cost_at(costs, current + 1)
        if ranges and ranges[-1][2] == value:
            start, _, old = ranges[-1]
            ranges[-1] = (start, current, old)
        else:
            ranges.append((current, current, value))
    return ranges


class ImprovementCatalog:
    def __init__(self, root):
        self.equipment = equipment_lookup.EquipmentCatalog(root)
        rows = json.loads((root / "data/equipment_upgrades.json").read_text(encoding="utf-8-sig"))
        self.upgrades = {row["eq_id"]: row for row in rows}
        self.families = {int(i): info["base"] for i, info in
                         json.loads((root / "data/fit_metadata.json").read_text(encoding="utf-8"))["ships"].items()}
        if len(self.upgrades) != len(rows):
            raise ValueError("개수 장비 ID 중복")
        self.validate()

    def validate(self):
        for item_id, row in self.upgrades.items():
            if item_id not in self.equipment.items:
                raise ValueError(f"개수 장비 미등록: {item_id}")
            for route in row["improvement"]:
                for helper in route["helpers"]:
                    if not set(helper["days"]) <= DAYS.keys():
                        raise ValueError("잘못된 개수 요일")
                for target in (*range(1, 11), 255):
                    cost = cost_at(route["costs"], target)
                    if cost is None:
                        continue
                    if any(n < 0 for n in cost[:4]):
                        raise ValueError("음수 개수 비용")
                    for equip_id, count in cost[4]:
                        if equip_id not in self.equipment.items or count < 0:
                            raise ValueError(f"개수 재료 장비 미등록: {equip_id}")
                    for consumable_id, count in cost[5]:
                        if consumable_id not in CONSUMABLES or count < 0:
                            raise ValueError(f"개수 특수재료 미등록: {consumable_id}")
                conversion = route.get("convert")
                if conversion and conversion["id_after"] not in self.equipment.items:
                    raise ValueError("개수 변환 장비 미등록")

    def item_name(self, item_id):
        return self.equipment.items[item_id]["name"]

    def cost_text(self, cost):
        if cost is None:
            return "비용 정보 없음"
        dev, dev_secure, screws, screws_secure, _, _ = cost
        return f"자재 {dev}/나사 {screws} (확정 시 {dev_secure}/{screws_secure})"

    def material_lines(self, cost):
        if cost is None:
            return []
        parts = [f"{self.item_name(i)} {n}개" for i, n in cost[4]]
        parts.extend(f"{CONSUMABLES[i]} {n}개" for i, n in cost[5])
        return [" · 소모아이템 : " + " / ".join(parts)] if parts else []

    def helpers_text(self, routes, ship_names, ship_forms):
        grouped = defaultdict(set)
        incomplete = False
        for route in routes:
            if not route["helpers"]:
                incomplete = True
            for helper in route["helpers"]:
                for ship_id in helper["ship_ids"]:
                    grouped[ship_id].update(helper["days"])
        lines = ["○ 2번함"]
        families = defaultdict(list)
        for ship_id, days in grouped.items():
            # IDs retain exact eligibility. Only presentation groups same-family
            # forms whose entire weekday sets are identical in this route.
            families[(self.families.get(ship_id, ship_id), frozenset(days))].append(ship_id)
        entries = []
        for (_, days), ids in families.items():
            ids.sort(key=lambda i: (ship_forms.get(i, ("", "", 0))[2], i))
            if len(ids) > 1 and all(i in ship_forms for i in ids):
                name = ship_forms[ids[0]][0] + "[" + "/".join(ship_forms[i][1] for i in ids) + "]"
            else:
                name = " / ".join(ship_names.get(i, f"함선 #{i}") for i in ids)
            text = "매일" if days == set(DAYS) else "".join(DAYS[d] for d in DAY_ORDER if d in days)
            sort_name = ship_forms[ids[0]][0] if ids[0] in ship_forms else name
            stage_order = ship_forms[ids[0]][2] if ids[0] in ship_forms else 0
            entries.append((sort_name, stage_order, f" - {name} ({text or '요일 미등록'})"))
        lines.extend(line for _, _, line in sorted(entries))
        if incomplete or not grouped:
            lines.append(" - 정보 없음")
        return lines

    def describe(self, item_id, ship_names, ship_forms=None):
        ship_forms = ship_forms or {}
        name = self.item_name(item_id)
        routes = self.upgrades.get(item_id, {}).get("improvement", [])
        if not routes:
            return f"{name}\n· 개수 정보 없음"
        # Group only identical full normal schedules, including ALL extra costs.
        schedules = {}
        for route in routes:
            costs = route["costs"]
            key = tuple(cost_at(costs, t) for t in range(1, 11))
            schedules.setdefault(key, []).append(route)
        lines = [name]
        for index, group in enumerate(schedules.values(), 1):
            if len(schedules) > 1:
                lines.extend(("", f"[개수 경로 {index}]"))
            costs = group[0]["costs"]
            for start, end, cost in star_ranges(costs):
                stars = f"★{start}" if start == end else f"★{start}~{end}"
                lines.append(f"{stars} - {self.cost_text(cost)}")
                lines.extend(self.material_lines(cost))
            lines.append("")
            lines.extend(self.helpers_text(group, ship_names, ship_forms))
        conversions = [r for r in routes if r.get("convert")]
        for index, route in enumerate(conversions, 1):
            conversion = route["convert"]
            stars = conversion["lvl_after"]
            after = self.item_name(conversion["id_after"]) + (f" ★{stars}" if stars else "")
            number = str(index) if len(conversions) > 1 else ""
            cost = cost_at(route["costs"], 255)
            lines.extend(("", f"※ 개수변환{number} - {after}", f"★max - {self.cost_text(cost)}"))
            lines.extend(self.material_lines(cost))
            if len(schedules) > 1:
                group_number = next(i for i, group in enumerate(schedules.values(), 1) if any(r is route for r in group))
                lines.append(f" · 개수 경로 {group_number}에서 변환")
            lines.append("")
            lines.extend(self.helpers_text([route], ship_names, ship_forms))
        if not conversions:
            lines.extend(("", "※ 개수변환 정보 없음"))
        return "\n".join(lines)

    def reply(self, query, ship_names, ship_forms=None):
        query = query.strip()
        if not query:
            return "사용법: !개수 [장비명]"
        hits = self.equipment.search(query)
        if len(hits) != 1:
            return self.equipment.reply(query).replace("!장비", "!개수")
        return self.describe(hits[0], ship_names, ship_forms)

    def describe_ship(self, ship_ids, base_name, ship_forms):
        """List equipment for exact second-ship forms, merging only equal weekdays."""
        forms = {ship_id: ship_forms[ship_id] for ship_id in ship_ids if ship_id in ship_forms}
        if not forms:
            return f"{base_name}\n· 등록된 2번함 개수 정보가 없습니다."
        lines = [f"{base_name} 개수 가능 장비"]
        for item_id, row in self.upgrades.items():
            by_form = defaultdict(set)
            for route in row['improvement']:
                for helper in route['helpers']:
                    for ship_id in helper['ship_ids']:
                        if ship_id in forms:
                            by_form[ship_id].update(helper['days'])
            if not by_form:
                continue
            by_days = defaultdict(list)
            for ship_id, days in by_form.items():
                by_days[frozenset(days)].append(ship_id)
            lines.append(f"· {self.item_name(item_id)}")
            for days, ids in sorted(by_days.items(), key=lambda entry: min(forms[i][2] for i in entry[1])):
                stages = '/'.join(forms[i][1] for i in sorted(ids, key=lambda i: (forms[i][2], i)))
                weekdays = '/'.join(DAYS[d] for d in DAY_ORDER if d in days)
                lines.append(f"  - {weekdays or '요일 미등록'} [{stages}]")
        if len(lines) == 1:
            lines.append('· 등록된 2번함 개수 정보가 없습니다.')
        return '\n'.join(lines)


@lru_cache(maxsize=1)
def catalog():
    return ImprovementCatalog(Path(__file__).parent)
