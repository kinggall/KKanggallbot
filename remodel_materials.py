"""Optional remodel costs; target-form references must agree with source costs."""
import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

MATERIALS = (
    "설계도", "전투상보", "캐터펄트", "신형포공병장자재",
    "신형항공병장자재", "신형병장자재", "개발자재", "고속건조재",
    "신형고온고압보일러", "해외함 최신기술", "개수자재", "공창자원",
)
CSV_FIELDS = {0: "改装設計図", 1: "戦闘詳報", 2: "カタパルト", 4: "新型航空兵装資材"}


def normalize(name):
    name = "".join(c for c in unicodedata.normalize("NFKD", name).casefold()
                   if not unicodedata.combining(c) and not c.isspace())
    return name.replace("吹雪改三護(六式)", "吹雪改三護")


@lru_cache(maxsize=1)
def reference():
    path = Path(__file__).parent / "data" / "ship_remodel_materials.csv"
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {normalize(row[2]): (int(row[5]), tuple(map(int, row[6:])))
                for row in csv.reader(file)}


def material_text(source, target):
    known = {}
    for index, field in CSV_FIELDS.items():
        match = re.search(r"\d+", str(source.get(field, "")))
        known[index] = int(match.group()) if match else 0
    try:
        item = reference().get(normalize(str(source.get("改装後", ""))))
    except (OSError, ValueError, IndexError):
        item = None
    # Only forward steps with matching level and independently recorded costs
    # may use the target's first-remodel reference. Backward/same-name links
    # and missing targets remain partial rather than reusing initial costs.
    complete = (
        target is not None and item is not None
        and normalize(source.get("艦名", "")) != normalize(source.get("改装後", ""))
        and str(item[0]) == str(source.get("改装Lv", ""))
        and all(item[1][index] == count for index, count in known.items())
    )
    counts = dict(enumerate(item[1])) if complete else known
    parts = [f"{MATERIALS[index]} {count}개" for index, count in counts.items() if count]
    if not complete:
        parts.append("기타 재료 미확인" if parts else "미확인")
    return "개장 재료: " + " / ".join(parts or ["없음"])
