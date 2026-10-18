"""Basic equipment lookup from the user's CP932 encyclopedia export."""
import csv
from functools import lru_cache
import json
from pathlib import Path
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


class EquipmentCatalog:
    def __init__(self, root):
        meta = json.loads((root / "data/fit_metadata.json").read_text(encoding="utf-8"))["equipment"]
        overrides_path = root / "data/equipment_name_overrides.json"
        overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
        self.items, self.names = {}, {}
        with (root / "equipments.csv").open(encoding="cp932", newline="") as file:
            reader = csv.DictReader(file)
            required = {"装備ID", "装備名", "射程", "配置コスト", "戦闘行動半径", *(field for field, _ in STATS)}
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
                aliases = {row["装備名"], name, translation.get("name", ""), translation.get("name_jp", "")}
                for alias in aliases:
                    key = normalize(alias)
                    if key:
                        self.names.setdefault(key, set()).add(item_id)

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
        candidates = set()
        for name, ids in self.names.items():
            if key in name:
                candidates.update(ids)
        return sorted(candidates)

    def describe(self, item_id):
        item = self.items[item_id]
        values = item["values"]
        stats = " / ".join(f"{label} {values[field]:+d}" for field, label in STATS if values[field])
        distance = values["射程"]
        details = (f"사거리 {RANGES.get(distance, str(distance))} / "
                   f"배치코스트 {values['配置コスト']} / 행동반경 {values['戦闘行動半径']}")
        return "\n".join((item["name"], stats or "기본 능력치: 모두 0", details))

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
