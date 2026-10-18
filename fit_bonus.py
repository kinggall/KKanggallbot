"""EO fit-rule lookup and condition rendering. All command data is local."""
from collections import OrderedDict
from functools import lru_cache
import json
import re
from pathlib import Path

STAT_NAMES = {"houg": "화력", "raig": "뇌장", "tyku": "대공", "souk": "장갑",
              "tais": "대잠", "kaih": "회피", "saku": "색적", "houm": "명중",
              "leng": "사거리", "baku": "폭장"}
RADARS = {"bonusSR": ("수상전탐", "los", 5), "bonusAR": ("대공전탐", "aa", 2),
          "bonusAccR": ("고명중전탐", "accuracy", 8)}
SELECTORS = {"shipX": "id", "shipS": "base", "shipClass": "ship_class",
             "shipType": "type", "shipNationality": "nationality"}
BONUS_FIELDS = {"bonus", *RADARS}
RULE_FIELDS = {*SELECTORS, *BONUS_FIELDS, "requires", "requiresLevel", "requiresNum",
               "requiresType", "requiresNumType", "level", "num"}


def add_stats(target, values, multiplier=1):
    for stat, value in values.items():
        target[stat] = target.get(stat, 0) + value * multiplier
    return target


def stats_text(values):
    return " / ".join(f"{name} {values[key]:+d}" for key, name in STAT_NAMES.items() if values.get(key))


def compact_line(condition, values):
    stats = stats_text(values).replace(" / ", " ").replace(" +", "+").replace(" -", "-")
    level = re.match(r"★(\d+) 이상 장비 기준 · ", condition)
    prefix = f"★{level[1]}: " if level else ""
    if level:
        condition = condition[level.end():]
    scope, _, requirement = condition.partition(" · 조건: ")
    once = "1회" in scope
    count = re.match(r"(\d+)개 이상", scope)
    if requirement:
        requirement = requirement.replace(" 함께 장착", " 병용").replace("대상 장비 자체도 인정", "자체 인정")
        requirement = requirement.replace("改二", "개2").replace("改三", "개3").replace("改", "개")
        if count:
            requirement = f"대상 장비 {count[1]}개 이상 + " + requirement
        label = " - " + (f"★{level[1]} 이상 · " if level else "") + requirement + " : "
        return label + stats + (" (1회만)" if once else "")
    if count:
        return prefix + f"· {count[1]}개 이상 장착 : 추가 " + stats + " (1회만)"
    if level:
        return prefix + "추가 " + stats + (" (1회만)" if once else "")
    if once:
        return "· " + stats + " (1회만)"
    return "· 1개당 : " + stats


class FitCatalog:
    def __init__(self, root):
        self.groups = json.loads((root / "fit_bonuses.json").read_text(encoding="utf-8-sig"))
        meta = json.loads((root / "fit_metadata.json").read_text(encoding="utf-8"))
        if meta["schema_version"] != 1:
            raise ValueError("지원하지 않는 피트 데이터 형식입니다.")
        self.ships, self.equipment, self.types = meta["ships"], meta["equipment"], meta["types"]
        for group in self.groups:
            if set(group) - {"ids", "types", "bonuses"}:
                raise ValueError("알 수 없는 피트 장비 조건입니다.")
            for rule in group["bonuses"]:
                if set(rule) - RULE_FIELDS:
                    raise ValueError("알 수 없는 피트 보너스 조건입니다.")
                for field in BONUS_FIELDS:
                    if set(rule.get(field, {})) - set(STAT_NAMES):
                        raise ValueError("알 수 없는 피트 능력치입니다.")

    def matches_ship(self, rule, ship_id):
        ship = dict(self.ships[str(ship_id)], id=int(ship_id))
        return all(field not in rule or ship[attr] in rule[field] for field, attr in SELECTORS.items())

    def can_equip(self, ship_id, item_id):
        ship = self.ships[str(ship_id)]
        item = self.equipment[str(item_id)]
        if str(item_id) in ship["expansion"]:
            return True
        category = str(item["type"])
        return category in ship["allowed"] and (
            ship["allowed"][category] is None or item_id in ship["allowed"][category])

    def is_radar(self, item_id, field):
        _, stat, minimum = RADARS[field]
        eq = self.equipment[str(item_id)]
        return eq["type"] in (12, 13, 93) and eq[stat] >= minimum

    def trigger_matches(self, group, item_id):
        return item_id in group.get("ids", []) or self.equipment[str(item_id)]["type"] in group.get("types", [])

    def calculate(self, ship_id, equipment):
        """Reference evaluator for verifying count/radar/upgrade rendering semantics."""
        total = {}
        for group in self.groups:
            for rule in group["bonuses"]:
                if not self.matches_ship(rule, ship_id):
                    continue
                if "requires" in rule:
                    count = sum(i in rule["requires"] and level >= rule.get("requiresLevel", 0)
                                for i, level in equipment)
                    if count < rule.get("requiresNum", 1):
                        continue
                if "requiresType" in rule:
                    count = sum(self.equipment[str(i)]["type"] in rule["requiresType"] for i, _ in equipment)
                    if count < rule.get("requiresNumType", 1):
                        continue
                count = sum(self.trigger_matches(group, i) and level >= rule.get("level", 0)
                            for i, level in equipment)
                if count < rule.get("num", 1):
                    continue
                once = any(k in rule for k in ("num", "requires", "requiresType"))
                add_stats(total, rule.get("bonus", {}), 1 if once else count)
                for field in RADARS:
                    if field in rule and any(self.is_radar(i, field) for i, _ in equipment):
                        add_stats(total, rule[field])
        return {k: v for k, v in total.items() if v}

    def item_name(self, item_id, ship_id=None):
        item = self.equipment[str(item_id)]
        name = item["name"]
        if ship_id is not None:
            ship = self.ships[str(ship_id)]
            category = str(item["type"])
            normal = category in ship["allowed"] and (
                ship["allowed"][category] is None or item_id in ship["allowed"][category])
            if not normal and str(item_id) in ship["expansion"]:
                star = ship["expansion"][str(item_id)]
                name += " (보강증설 전용" + (f"·★{star} 이상" if star else "") + ")"
        return name

    def condition_text(self, rule, field, targets=(), ship_id=None):
        once = any(k in rule for k in ("num", "requires", "requiresType"))
        number, level = rule.get("num", 1), rule.get("level", 0)
        if number > 1:
            scope = f"{number}개 이상 장착 시 추가(1회)"
        elif once:
            scope = "장착 시 추가(1회)"
        else:
            scope = "1개당"
        if level:
            scope = f"★{level} 이상 장비 기준 · " + scope
        conditions = []
        if "requires" in rule:
            names = " 또는 ".join(self.item_name(i, ship_id) for i in rule["requires"])
            star = f"★{rule['requiresLevel']} 이상 " if rule.get("requiresLevel") else ""
            conditions.append(f"{names} 중 {star}총 {rule.get('requiresNum', 1)}개 이상 장착")
        if "requiresType" in rule:
            names = " 또는 ".join(self.types[str(t)] for t in rule["requiresType"])
            conditions.append(f"{names} 중 총 {rule.get('requiresNumType', 1)}개 이상 장착")
        if field in RADARS:
            if any(self.is_radar(i, field) for i in targets):
                conditions.append(RADARS[field][0] + " 장착(대상 장비 자체도 인정)")
            else:
                conditions.append(RADARS[field][0] + " 함께 장착")
            if not once:
                scope = "추가(1회)" if not level else f"★{level} 이상 장비 기준 · 추가(1회)"
        return scope + (" · 조건: " + " + ".join(conditions) if conditions else "")

    @lru_cache(maxsize=1024)
    def blocks_for_ship(self, ship_id):
        if str(ship_id) not in self.ships:
            raise ValueError(f"함선 ID {ship_id}의 피트 판정 정보가 없습니다.")
        possible = {int(i) for i in self.equipment if self.can_equip(ship_id, int(i))}
        by_type = {}
        for item in possible:
            by_type.setdefault(self.equipment[str(item)]["type"], set()).add(item)
        radars = {field: any(self.is_radar(i, field) for i in possible) for field in RADARS}
        blocks = []
        for group in self.groups:
            targets = possible.intersection(group.get("ids", []))
            for category in group.get("types", []):
                targets.update(by_type.get(category, set()))
            if not targets:
                continue
            if group.get("ids"):
                ids = [i for i in group["ids"] if i in targets]
                title = " / ".join(self.item_name(i, ship_id) for i in ids)
                if len(ids) > 1:
                    title += " (대상 장비 합산 개수)"
            else:
                categories = sorted({self.equipment[str(i)]["type"] for i in targets})
                title = " / ".join(self.types[str(t)] for t in categories) + " (장착 가능한 종류 공통)"
            lines = OrderedDict()
            for rule in sorted(group["bonuses"], key=lambda r: (
                    bool(r.get("requires") or r.get("requiresType")),
                    r.get("level", 0), r.get("num", 1))):
                if not self.matches_ship(rule, ship_id):
                    continue
                if rule.get("num", 1) > self.ships[str(ship_id)]["slots"] + 1:
                    continue
                if "requires" in rule and not possible.intersection(rule["requires"]):
                    continue
                if "requiresType" in rule and not any(self.equipment[str(i)]["type"] in rule["requiresType"] for i in possible):
                    continue
                for field in ("bonus", *RADARS):
                    if not rule.get(field):
                        continue
                    if field in RADARS and not radars[field]:
                        continue
                    condition = self.condition_text(rule, field, targets, ship_id)
                    add_stats(lines.setdefault(condition, {}), rule[field])
            rendered = [compact_line(condition, values) for condition, values in lines.items() if stats_text(values)]
            if rendered:
                blocks.append((title, rendered))
        return blocks

    def message(self, keyword, forms):
        """One message; identical equipment rules shared across forms appear only once."""
        unique = OrderedDict()
        for ship_id, stage in forms:
            occurrences = {}
            blocks = self.blocks_for_ship(ship_id)
            if not blocks:
                blocks = [("등록된 장착 가능 피트 보너스 없음", [])]
            for title, lines in blocks:
                key = (title, tuple(lines))
                occurrence = occurrences.get(key, 0)
                occurrences[key] = occurrence + 1
                unique.setdefault((title, tuple(lines), occurrence), []).append(stage)
        sections = OrderedDict()
        for (title, lines, _occurrence), stages in unique.items():
            sections.setdefault(tuple(stages), []).append((title, lines))
        output = [f"{keyword} 피트"]
        for stages, blocks in sorted(sections.items(), key=lambda item: -len(item[0])):
            entries = []
            for title, lines in blocks:
                title = title.replace("改二", "개2").replace("改三", "개3").replace("改", "개")
                title = re.sub(r"\s+\(", "(", title).strip()
                if len(lines) == 1 and lines[0].startswith("· ") and "1개당" not in lines[0]:
                    entries.append(title + ": " + lines[0][2:])
                else:
                    entries.append(title + ("\n" + "\n".join(lines) if lines else ""))
            output.append("[" + " / ".join(stages) + "]\n" + "\n\n".join(entries))
        output.append("※ ★보정은 해당 ★ 이상 장비마다 추가하며, (1회만)은 한 번만 적용합니다.\n종류 공통·개별·조건별 보너스는 합산합니다.")
        return "\n\n".join(output)

@lru_cache(maxsize=1)
def catalog():
    return FitCatalog(Path(__file__).parent / "data")


def format_message(keyword, forms):
    return catalog().message(keyword, forms)
