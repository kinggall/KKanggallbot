"""Basic equipment lookup from the user's CP932 encyclopedia export."""
import csv
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

STATS = (("火力", "화력"), ("雷装", "뇌장"), ("対空", "대공"),
         ("装甲", "장갑"), ("対潜", "대잠"), ("回避", "회피"),
         ("索敵", "색적"), ("命中", "명중"), ("爆装", "폭장"), ("運", "운"))
RANGES = {0: "없음", 1: "단", 2: "중", 3: "장", 4: "초장", 5: "초장+"}


def display_name(name):
    return name.replace("改二", "개2").replace("改三", "개3").replace("改", "개").strip()


def normalize(name):
    for full, short in (("함상전투기", "함전"), ("함상폭격기", "함폭"), ("함상공격기", "함공"),
                        ("삼연장", "3연장"), ("사연장", "4연장"), ("오연장", "5연장"),
                        ("육연장", "6연장"), ("삼식탄", "3식탄")):
        name = name.replace(full, short)
    value = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", name).casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn"
                   and (char.isalnum() or char in ".+"))


def gun_short_name(name):
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"(?<=\d)\s*cm", "", value)
    return normalize(value.replace("포", "").replace("砲", ""))


def is_gun_short_query(query):
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", query).casefold())
    return bool(re.search(r"\d+(?:\.\d+)?(?:cm)?(?:단장|(?:\d+|[삼사오육칠팔구])?연장)", value))


class EquipmentCatalog:
    def __init__(self, root):
        meta = json.loads((root / "data/fit_metadata.json").read_text(encoding="utf-8"))["equipment"]
        overrides_path = root / "data/equipment_name_overrides.json"
        overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
        aliases_path = root / "data/equipment_aliases.json"
        aliases_by_name = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
        if not isinstance(aliases_by_name, dict):
            raise ValueError("장비 별명 파일의 최상위 형식은 객체여야 합니다.")
        self.items, self.names, self.gun_names = {}, {}, {}
        known_jp_names = set()
        with (root / "equipments.csv").open(encoding="cp932", newline="") as file:
            reader = csv.DictReader(file)
            required = {"装備ID", "装備名", "装備種3", "射程", "配置コスト", "戦闘行動半径", *(field for field, _ in STATS)}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("장비 CSV에 필요한 컬럼이 없습니다.")
            for row in reader:
                item_id = int(row["装備ID"])
                if not 0 < item_id < 1500:
                    continue
                if item_id in self.items:
                    raise ValueError(f"중복 장비 ID: {item_id}")
                translation = meta.get(str(item_id), {})
                name = display_name(overrides.get(str(item_id), translation.get("name", row["装備名"])))
                values = {field: int(row[field]) for field in required - {"装備名"}}
                self.items[item_id] = dict(name=name, values=values)
                jp_name = row["装備名"]
                known_jp_names.add(jp_name)
                aliases = {row["装備名"], name, translation.get("name", ""), translation.get("name_jp", "")}
                custom_aliases = aliases_by_name.get(jp_name, [])
                if not isinstance(custom_aliases, list) or not all(isinstance(alias, str) for alias in custom_aliases):
                    raise ValueError(f"{jp_name} 별명은 문자열 목록이어야 합니다.")
                aliases.update(custom_aliases)
                for alias in aliases:
                    key = normalize(alias)
                    if key:
                        self.names.setdefault(key, set()).add(item_id)
                    if values["装備種3"] in (1, 2, 3) and re.search(r"\d\s*cm", alias, re.I):
                        self.gun_names.setdefault(gun_short_name(alias), set()).add(item_id)
        unknown_names = set(aliases_by_name) - known_jp_names
        if unknown_names:
            raise ValueError("장비 별명 파일에 CSV에 없는 일본어 장비명이 있습니다: " + ", ".join(sorted(unknown_names)))

    def search(self, query):
        query = query.strip()
        if query.startswith("#") and query[1:].isdigit():
            item_id = int(query[1:])
            return [item_id] if item_id in self.items else []
        key = normalize(query)
        if not key:
            return []
        if key in self.names:
            return sorted(self.names[key])
        gun_key = gun_short_name(query) if is_gun_short_query(query) else ""
        if gun_key in self.gun_names:
            return sorted(self.gun_names[gun_key])
        candidates = set()
        for name, ids in self.names.items():
            if key in name:
                candidates.update(ids)
        if gun_key:
            gun_pattern = re.compile(r"(?<![\d.])" + re.escape(gun_key))
            for name, ids in self.gun_names.items():
                if gun_pattern.search(name):
                    candidates.update(ids)
        return sorted(candidates)

    def describe(self, item_id):
        item = self.items[item_id]
        values = item["values"]
        stats = " / ".join(f"{label} {values[field]:+d}" for field, label in STATS if values[field])
        distance = values["射程"]
        details = []
        if distance:
            details.append(f"사거리 {RANGES.get(distance, str(distance))}")
        for field, label in (("配置コスト", "배치코스트"), ("戦闘行動半径", "행동반경")):
            if values[field]:
                details.append(f"{label} {values[field]}")
        effects = {42: "(1회 부활 - 대파 상태)", 43: "(1회 부활 - 완전 회복)"}
        lines = [item["name"], "· " + (stats or "능력치 없음" + effects.get(item_id, ""))]
        if details:
            lines.append("· " + " / ".join(details))
        return "\n".join(lines)

    def reply(self, query):
        query = query.strip()
        if not query:
            return "사용법: !장비 장비명"
        results = self.search(query)
        if not results:
            return f"'{query}' 장비를 찾지 못했습니다."
        if len(results) == 1:
            return self.describe(results[0])
        lines = [f"'{query}' 검색 결과 {len(results)}개. 이름을 더 자세히 입력해주세요."]
        lines.extend(f"· {self.items[item_id]['name']} (#{item_id})" for item_id in results[:10])
        if len(results) > 10:
            lines.append(f"외 {len(results) - 10}개")
        lines.append("번호 검색 예: !장비 #" + str(results[0]))
        return "\n".join(lines)


@lru_cache(maxsize=1)
def catalog():
    return EquipmentCatalog(Path(__file__).parent)


def build_reply(query):
    return catalog().reply(query)
