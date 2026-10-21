"""Offline quest lookup using TsunKit quest facts and EO Korean translations.

SPDX-License-Identifier: GPL-3.0-only
Source priority, identity decisions and limitations: QUEST_DATA.md.
"""
from collections import defaultdict
from functools import lru_cache
import html
import json
from pathlib import Path
import re
import unicodedata

import equipment_lookup

USAGE = "사용법: !임무 [임무번호/임무명]\n예: !임무 B100 / !임무 해상호위총대"
UNVERIFIED = "※ 선행조건 등이 검증중인 임무입니다."
FREQUENCY = {"onetime": "단발", "daily": "일간", "weekly": "주간", "monthly": "월간",
             "quarterly": "계간", "annual": "연간", "event": "기간한정", "seasonal": "기간한정",
             "special1": "일간", "special2": "일간"}
SHIP_TYPES = {1: "해방", 2: "구축", 3: "경순", 4: "뇌순", 5: "중순", 6: "항순", 7: "경항모",
              8: "고속전함", 9: "저속전함", 10: "항전", 11: "정규항모", 12: "초노급전함",
              13: "잠수함", 14: "잠수항모", 16: "수모", 17: "상륙함", 18: "장갑항모",
              19: "공작함", 20: "잠수모함", 21: "연순", 22: "보급함"}
INVENTORY = {1: "고속수복재", 2: "고속건조재", 3: "개발자재", 4: "개수자재",
             10: "가구함(소)", 11: "가구함(중)", 12: "가구함(대)",
             31: "연료", 32: "탄약", 33: "강재", 34: "보키", 44: "가구코인",
             49: "도크 개방키", 50: "응급수리요원", 51: "응급수리여신", 52: "특수가구장인",
             53: "모항 확장", 54: "마미야", 55: "서류 일식 & 반지", 56: "칸무스의 초콜릿",
             57: "훈장", 58: "설계도", 59: "이라코", 60: "선물상자", 61: "갑종훈장",
             62: "히시모치", 63: "사령부요원", 64: "보강증설", 65: "시제갑판 캐터펄트",
             66: "전투식량", 67: "양상보급", 68: "꽁치", 69: "꽁치 통조림", 70: "숙련탑승원",
             71: "네식 엔진", 72: "장식 재료", 73: "설영대", 74: "신형항공기설계도",
             75: "신형포공병장자재", 76: "전투식량(특별한 주먹밥)", 77: "신형항공병장자재",
             78: "전투상보", 79: "해협장", 80: "크리스마스 선물상자", 85: "쌀", 86: "매실장아찌",
             87: "김", 88: "차", 89: "호쇼의 저녁 식권", 90: "절분의 콩", 91: "긴급수리자재",
             92: "신형분진장비개발자재", 93: "정어리", 94: "신형병장자재", 95: "잠수함보급물자",
             96: "호박", 97: "테루테루보즈", 98: "바다색 리본", 99: "흰 어깨띠",
             100: "해외함 최신기술", 101: "야간숙련탑승원", 102: "항공특별증가식",
             103: "공창확장키", 104: "공창자원", 105: "격납고 증설"}
RESOURCES = ("연료", "탄약", "강재", "보키")
FEATURES = {1: "제2함대 개방", 2: "제3함대 개방", 3: "제4함대 개방", 4: "개수공창 개방",
            6: "중부해역 기지항공대 개방", 8: "남서해역 기지항공대 개방"}
EQUIP_GROUPS = {1: "소구경주포", 2: "중구경주포", 3: "대구경주포", 4: "부포",
                6: "함상전투기", 7: "함상폭격기", 8: "함상공격기", 9: "함상정찰기",
                10: "수상정찰기", 11: "수상폭격기", 12: "소형전탐", 13: "대형전탐",
                5: "어뢰", 15: "폭뢰", 16: "벌지", 17: "기관부강화", 21: "기총", 47: "육상공격기",
                -12: "전탐"}


def normalized(value):
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(c for c in text if c.isalnum())


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def values(value):
    return value if isinstance(value, list) else [value]


def natural_code(value):
    return tuple((1, int(x)) if x.isdigit() else (0, x.casefold()) for x in re.split(r"(\d+)", value))


class UnsupportedCondition(ValueError):
    pass


class QuestCatalog:
    def __init__(self, root):
        root = Path(root)
        self.data = json.loads((root / "data/quests.json").read_text(encoding="utf-8"))
        if self.data.get("schema") != 1:
            raise ValueError("임무 자료 형식 오류")
        self.items, self.codes = self.data["quests"], self.data["codes"]
        self.labels = self.data["labels"]
        self.equipment = equipment_lookup.EquipmentCatalog(root)
        self.aliases = json.loads((root / "data/ship_aliases.json").read_text(encoding="utf-8"))
        self.by_code, self.after = {}, defaultdict(set)
        for key, row in self.items.items():
            if str(row["game_id"]) != key or row["frequency"] not in FREQUENCY:
                raise ValueError(f"잘못된 임무 ID/주기: {key}")
            for code in [row["wiki_id"], *row.get("aliases", [])]:
                code = code.strip().casefold()
                if code in self.by_code and self.by_code[code] != key:
                    raise ValueError(f"중복 임무 번호: {code}")
                self.by_code[code] = key
            for before in row["prereqs"]:
                if str(before) not in self.codes or before == row["game_id"]:
                    raise ValueError(f"선행 임무 번호 누락/자기참조: {key}: {before}")
                self.after[str(before)].add(key)

    def ship_name(self, item_id):
        name = self.labels["ships"].get(str(item_id), f"함선 #{item_id}")
        # The aliases are per family; do not substitute a base alias for an
        # explicitly remodeled ship. Use them only for an exact Japanese name.
        if name in self.aliases:
            name = next((a for a in self.aliases[name] if re.search(r"[가-힣]", a)), name)
        return equipment_lookup.display_name(name)

    def family_name(self, item_id):
        jp = self.labels["families"].get(str(item_id), "")
        if jp.endswith("型") and jp[:-1] in self.aliases:
            name = next((a for a in self.aliases[jp[:-1]] if re.search(r"[가-힣]", a)), jp[:-1])
            return name + "급"
        if not jp:
            raise UnsupportedCondition("함급 정보 없음")
        return jp

    def group_name(self, group):
        ids = set(values(group))
        if ids == {4001, 4002, 4004, 4005}:
            return "미국/영국/호주/네덜란드함"
        names = {1100: "고속함", 4001: "미국함", 4002: "영국함", 4003: "프랑스함"}
        if not ids <= names.keys():
            raise UnsupportedCondition("함선 그룹 정보 없음")
        return "/".join(names[i] for i in values(group))

    def selector(self, rule):
        parts = []
        for field, func in (("ship_id", self.ship_name), ("class_id", lambda i: SHIP_TYPES[i]),
                            ("family_id", self.family_name)):
            if field in rule:
                parts.append("/".join(func(i) for i in values(rule[field])))
        if "group_id" in rule:
            parts.append(self.group_name(rule["group_id"]))
        if "criteria" in rule:
            if set(rule["criteria"]) != {"group_id"}:
                raise UnsupportedCondition("추가 편성 조건 미지원")
            parts.append(self.group_name(rule["criteria"]["group_id"]))
        return " · ".join(parts) or "자유"

    def composition(self, rule):
        label = self.selector(rule)
        amount = rule.get("amount")
        if isinstance(amount, list):
            amount = str(amount[0]) if amount[0] == amount[1] else f"{amount[0]}~{amount[1]}"
        if amount is not None:
            if "ship_id" in rule or "family_id" in rule or "group_id" in rule:
                label += f" 중 {amount}척"
            else:
                label += str(amount)
        if rule.get("otherships") and label != "자유" and any(k in rule for k in ("ship_id", "class_id", "family_id", "group_id")):
            label += "(추가)"
        if "position" in rule:
            pos = rule["position"]
            label += "(기함)" if pos == 1 else f"({pos}번함)"
        if "lv" in rule:
            lv = rule["lv"]
            label += f" Lv{lv[0]} 이상" if lv[1] >= 999 else f" Lv{lv[0]}~{lv[1]}"
        return label

    def item_name(self, row):
        kind, item_id = row.get("category"), row.get("id")
        if kind == "equipment":
            name = self.equipment.items.get(item_id, {}).get("name", row.get("name") or f"장비 #{item_id}")
        elif kind == "ship":
            name = self.ship_name(item_id)
        elif kind == "inventory":
            name = INVENTORY.get(item_id, self.labels["inventory"].get(str(item_id), row.get("name") or f"아이템 #{item_id}"))
        elif kind == "furniture":
            name = row.get("name") or self.labels["furniture"].get(str(item_id), f"가구 #{item_id}")
        elif kind == "feature":
            name = FEATURES.get(item_id, f"기능 개방 #{item_id}")
        elif kind == "senka":
            name = "전과"
        elif kind == "equipgroup":
            if item_id not in EQUIP_GROUPS:
                raise UnsupportedCondition("장비 그룹 정보 없음")
            name = EQUIP_GROUPS[item_id]
        elif "class_id" in row:
            name = "/".join(SHIP_TYPES[i] for i in values(row["class_id"]))
        else:
            raise UnsupportedCondition("아이템 분류 미지원")
        if row.get("stars"):
            name += f" ★{row['stars']}"
        if "amount" in row:
            name += f" {row['amount']}"
        return name

    def resource_line(self, amounts):
        return "/".join(f"{label} {n}" for label, n in zip(RESOURCES, amounts) if n)

    def requirements(self, req):
        kind, lines = req["category"], []
        if kind in ("and", "or", "then"):
            for i, branch in enumerate(req["list"], 1):
                if len(req["list"]) > 1:
                    lines.append({"and": f"조건 {i} (모두 필요)", "or": f"편성안 {i} (택1)",
                                  "then": f"{i}단계 (순서대로)"}[kind])
                lines.extend(self.requirements(branch))
            return lines
        supported = {"category", "comp", "fleet_id", "disallowed", "comp_banned", "sortie", "subcategory",
                     "times", "group_id", "amount", "result", "daily", "victory", "expeds", "resources",
                     "secretary", "slots", "scrap", "consume", "batch", "secretary_banned", "class_id", "family_id", "id", "list"}
        if set(req) - supported:
            raise UnsupportedCondition("추가 조건 필드")
        if req.get("fleet_id", 1) != 1:
            lines.append(f"제{req['fleet_id']}함대")
        if req.get("comp"):
            lines.append(" + ".join(self.composition(c) for c in req["comp"]))
        if req.get("comp_banned"):
            lines.append("편성 제외: " + " / ".join(self.selector(c) for c in req["comp_banned"]))
        if req.get("disallowed"):
            lines.append({"aviation": "항공전력 편성 불가", "carriers": "항모 편성 불가",
                          "otherships": "지정 함선 외 편성 불가"}[req["disallowed"]])
        if kind == "sortie":
            for row in req.get("sortie", []):
                maps = "/".join(map(str, values(row["map"]))) if "map" in row else "해역 무관"
                node = f" {str(row['node']).upper()}지점" if "node" in row else (" 보스" if row.get("boss") else "")
                result = row.get("result")
                victory = " 도달" if result == "clear" else (f" {result}승" + (" 이상" if result != "S" else "") if result else " 도달")
                if result is None and "node" not in row and not row.get("boss"):
                    victory = " 전투"
                count = ""
                if "times" in row:
                    count = (" 합계 " if row.get("any") else " 각 " if isinstance(row.get("map"), list) else " ") + f"{row['times']}회"
                lines.append(maps + node + victory + count)
            if not req.get("sortie"):
                raise UnsupportedCondition("해역 조건 누락")
        elif kind == "sink":
            targets = {5011: "적 항모", 5013: "적 잠수함", 5015: "적 수송함"}
            lines.append(f"{targets[req['group_id']]} {req['amount']}척 격침")
        elif kind == "exercise":
            result = req.get("result", "B")
            when = "오늘 중 " if req.get("daily") else ""
            lines.append(f"{when}연습 {result}승" + (" 이상" if result != "S" else "") + f" {req.get('times', 1)}회")
        elif kind == "expedition":
            for row in req["expeds"]:
                ids = "/".join(map(str, values(row["id"]))) if "id" in row else "종류 무관"
                result = "대성공" if req.get("result") == "S" else "성공"
                lines.append(f"원정 {ids} {result} {row.get('times', 1)}회")
        elif kind == "simple":
            action = {"battle": "전투", "resupply": "보급", "repair": "입거 수리", "ship": "건조",
                      "equipment": "장비 개발", "scrapship": "해체", "scrapequipment": "장비 폐기",
                      "improvement": "장비 개수", "modernization": "근대화개수 성공"}[req["subcategory"]]
            lines.append(f"{action} {req['times']}회" + (" (한 번에)" if req.get("batch") else ""))
        elif kind == "modernization":
            lines.append(self.selector(req) + f" 근대화개수 성공 {req['times']}회")
        elif kind == "scrapequipment":
            lines.append("폐기: " + " / ".join(self.item_name(x) for x in req.get("list", [])))
        elif kind in ("equipgroup", "equipment"):
            lines.append("장비 준비: " + self.item_name({**req, "category": kind}))
        elif kind not in ("fleet", "conversion", "equipexchange", "scrapequipment"):
            raise UnsupportedCondition("임무 유형 미지원")
        if req.get("secretary"):
            lines.append("비서함: " + self.selector(req["secretary"]))
        if req.get("secretary_banned"):
            lines.append("비서함 제외: " + self.selector(req["secretary_banned"]))
        for slot in req.get("slots", []):
            equip = {**slot, "category": "equipment"}
            text = f"{slot['slot']}번 슬롯: " if slot.get("slot") else "장착: "
            text += self.item_name(equip)
            if slot.get("fullyskilled"):
                text += " (숙련도 최대)"
            if slot.get("conversion"):
                text += " (전환 시 개수 유지)" if slot["conversion"] == "starskept" else " (전환 시 개수 초기화)"
            lines.append(text)
        for field, label in (("scrap", "폐기"), ("consume", "소모")):
            if req.get(field):
                lines.append(label + ": " + " / ".join(self.item_name(x) for x in req[field]))
        if any(req.get("resources", [])):
            lines.append("준비 자원: " + self.resource_line(req["resources"]))
        return lines

    def detail(self, key):
        row = self.items[key]
        tags = FREQUENCY[row["frequency"]] + ("/종료" if row.get("unavailable") else "")
        lines = [f"{row['wiki_id']}: {clean(row['name_ko'])} ({tags})", "", "[조건]"]
        if row["frequency"] in ("special1", "special2"):
            lines.append("· 출현: 날짜 끝자리 " + ("3/7/0" if row["frequency"] == "special1" else "2/8"))
        try:
            requirements = self.requirements(row["requirements"])
        except (UnsupportedCondition, KeyError):
            requirements = [clean(row["description"]) or "상세 조건 미등록"]
        lines.extend("· " + text for text in requirements or [clean(row["description"]) or "상세 조건 미등록"])
        lines.extend(["", "[보상]"])
        resources = self.resource_line(row["rewards"]["resources"])
        if resources:
            lines.append("· " + resources)
        other = row["rewards"]["other"]
        choice_count = sum("choices" in reward for reward in other)
        n = 0
        for reward in other:
            if "choices" in reward:
                n += 1
                label = f"선택{n}" if choice_count > 1 else "선택"
                lines.append("· " + label + ": " + " / ".join(self.item_name(x) for x in reward["choices"]) + " (택1)")
            else:
                if reward.get("category") == "feature" and reward.get("id") == 5:
                    # Upstream uses #5 for both unrelated unlocks.
                    name = {"D25": "원정 자동보급 개방", "F10": "대형함 건조 개방"}.get(row["wiki_id"], "기능 개방")
                    lines.append("· " + name)
                else:
                    lines.append("· " + self.item_name(reward))
        if not resources and not other:
            lines.append("· 보상 정보 없음")
        lines.extend(["", "[선행조건]"])
        before = [self.codes[str(i)] for i in row["prereqs"]]
        lines.append(" + ".join(before) if before else "등록 정보 없음")
        lines.extend(["", "[후속임무]"])
        after = sorted((self.items[i]["wiki_id"] for i in self.after[key]), key=natural_code)
        lines.append(" / ".join(after) if after else "등록 정보 없음")
        if row["unverified"]:
            lines.extend(["", UNVERIFIED])
        return "\n".join(lines)

    def reply(self, query):
        query = query.strip()
        if not query:
            return USAGE
        key = self.by_code.get(query.casefold())
        if key:
            return self.detail(key)
        needle = normalized(query)
        if not needle:
            return USAGE
        found = [key for key, row in self.items.items()
                 if any(needle in normalized(row.get(field, "")) for field in ("name_ko", "name_jp"))]
        found.sort(key=lambda k: natural_code(self.items[k]["wiki_id"]))
        if len(found) == 1:
            return self.detail(found[0])
        if not found:
            return f"'{query}' 임무를 찾지 못했습니다.\n" + USAGE
        lines = [f"'{query}' 검색 결과 {len(found)}개. 임무 번호를 입력해주세요."]
        lines.extend(f"· {clean(self.items[k]['name_ko'])} ({self.items[k]['wiki_id']})" for k in found[:30])
        if len(found) > 30:
            lines.append("이름을 더 자세히 입력해주세요.")
        lines.append("번호 검색 예: !임무 " + self.items[found[0]]["wiki_id"])
        return "\n".join(lines)


@lru_cache(maxsize=1)
def catalog():
    return QuestCatalog(Path(__file__).resolve().parent)
