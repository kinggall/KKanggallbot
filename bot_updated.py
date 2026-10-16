from flask import Flask, request, jsonify
import requests
import random
import re
import json
import csv
from pathlib import Path

app = Flask(__name__)

IRIS_REPLY_URL = "http://127.0.0.1:3000/reply"

CSV_FILE = Path(__file__).parent / "ships.csv"
SHIP_KO_FILE = Path(__file__).parent / "data" / "ship-ko.json"
SHIP_ALIASES_FILE = Path(__file__).parent / "ship_aliases.json"
SHIP_KO_URL = "https://raw.githubusercontent.com/kinggall/Data/master/Translations/ko-KR/ship.json"


def load_ship_data():
    """업로드한 Shift-JIS 칸무스 CSV와 한국어 번역을 사용합니다."""
    with open(CSV_FILE, encoding="cp932", newline="") as file:
        ships = list(csv.DictReader(file))

    SHIP_KO_FILE.parent.mkdir(exist_ok=True)
    if not SHIP_KO_FILE.exists():
        response = requests.get(SHIP_KO_URL, timeout=20)
        response.raise_for_status()
        SHIP_KO_FILE.write_bytes(response.content)
    with open(SHIP_KO_FILE, encoding="utf-8-sig") as file:
        translations = json.load(file).get("ship", {})

    # Electronic Observer의 선박 ID 1501 이상은 심해서함입니다.
    # 일반 칸무스 검색에서는 심해서함을 제외합니다.
    ships = [
        ship for ship in ships
        if int(ship.get("艦船ID", "0") or 0) <= 1500
    ]
    return ships, translations


try:
    SHIPS, SHIP_TRANSLATIONS = load_ship_data()
    print(f"[함선 데이터] 일반 칸무스 {len(SHIPS)}개 로드 완료 (심해서함 제외)")
except Exception as error:
    SHIPS = []
    SHIP_TRANSLATIONS = {}
    print(f"[함선 데이터] 로드 실패: {error}")

try:
    with open(SHIP_ALIASES_FILE, encoding="utf-8") as file:
        SHIP_ALIASES = json.load(file)
    print(f"[함선 별명] {len(SHIP_ALIASES)}개 함선 등록 완료")
except Exception as error:
    SHIP_ALIASES = {}
    print(f"[함선 별명] 로드 실패: {error}")


def normalize_ship_name(value):
    """검색용 이름 정규화: 로-500/로500, U-511/U511 등을 같은 검색어로 봅니다."""
    value = str(value or "").strip().casefold()
    return re.sub(r"[\s\-_・·.]+", "", value)


def build_ship_graph():
    """행 번호를 노드로 사용해 같은 이름이 여러 번 나와도 누락하지 않습니다."""
    name_to_indexes = {}
    for index, ship in enumerate(SHIPS):
        name = str(ship.get("艦名", "")).strip()
        name_to_indexes.setdefault(name, set()).add(index)

    graph = {index: set() for index in range(len(SHIPS))}
    for index, ship in enumerate(SHIPS):
        for field in ("改装前", "改装後"):
            linked_name = str(ship.get(field, "")).strip()
            if not linked_name or linked_name == "-":
                continue
            for linked_index in name_to_indexes.get(linked_name, set()):
                graph[index].add(linked_index)
                graph[linked_index].add(index)
    return graph


SHIP_GRAPH = build_ship_graph()


def search_ships(keyword):
    query = normalize_ship_name(keyword)
    seed_indexes = set()
    aliases_to_names = {}
    for canonical_name, aliases in SHIP_ALIASES.items():
        for alias in aliases:
            aliases_to_names.setdefault(normalize_ship_name(alias), set()).add(canonical_name)

    for index, ship in enumerate(SHIPS):
        name_jp = str(ship.get("艦名", ""))
        name_ko = SHIP_TRANSLATIONS.get(name_jp, "")
        registered_names = aliases_to_names.get(query, set())
        if query in {
            normalize_ship_name(name_jp),
            normalize_ship_name(name_ko),
        } or name_jp in registered_names:
            seed_indexes.add(index)

    related_indexes = set(seed_indexes)
    pending = list(seed_indexes)
    while pending:
        current = pending.pop()
        for related in SHIP_GRAPH.get(current, set()):
            if related not in related_indexes:
                related_indexes.add(related)
                pending.append(related)

    results = [
        (SHIPS[index], SHIP_TRANSLATIONS.get(str(SHIPS[index].get("艦名", "")),
                                              str(SHIPS[index].get("艦名", ""))))
        for index in related_indexes
    ]
    results.sort(key=lambda item: (
        int(item[0].get("改装段階", "0") or 0),
        int(item[0].get("艦船ID", "0") or 0),
    ))
    return results


def ship_stage(ship):
    stage = int(ship.get("改装段階", "0") or 0)
    name = str(ship.get("艦名", ""))

    special_stages = {
        "千歳": {
            0: "미개장", 1: "개1", 2: "갑", 3: "항", 4: "항개", 5: "항개2"
        },
        "千代田": {
            0: "미개장", 1: "개1", 2: "갑", 3: "항", 4: "항개", 5: "항개2"
        },
        "夕張": {
            0: "미개장", 1: "개1", 2: "개2", 3: "개2특", 4: "개2정"
        },
        "宗谷": {
            0: "미개장", 1: "특무함", 2: "등대보급선", 3: "남극관측선"
        },
        "Glorious": {
            0: "미개장", 1: "항모", 2: "개1(정규항모)", 3: "개1(순양전함)"
        },
        "Glorious改": {
            2: "개1(정규항모)", 3: "개1(순양전함)"
        },
    }
    for special_name, labels in special_stages.items():
        if name == special_name and stage in labels:
            return labels[stage]
    if stage == 0:
        return "미개장"
    # 改三護처럼 일반적인 단계 번호와 다른 특수 개장 명칭만 개3호로 표시합니다.
    if "改三護" in name:
        return "개3호"
    return f"개{stage}"


def ship_text(ship, name_ko):
    stage = ship_stage(ship)
    next_ship_name = ship.get("改装後", "-")
    next_level = ship.get("改装Lv", "-")

    result = [
        f"[{stage}]",
        f"화력 {ship.get('火力最大', '-')} / 뇌장 {ship.get('雷装最大', '-')} / "
        f"대공 {ship.get('対空最大', '-')} / 장갑 {ship.get('装甲最大', '-')}"
    ]
    if next_ship_name not in ("", "-") and next_level not in ("", "0", "-"):
        next_stage = next(
            (ship_stage(candidate) for candidate in SHIPS
             if candidate.get("艦名") == next_ship_name),
            "개장"
        )
        result.append(f"{next_stage} 개장 레벨: {next_level}")
    return "\n".join(result)

PANTY_COLORS = [
    "빨강",
    "주황",
    "노랑",
    "초록",
    "파랑",
    "남색",
    "보라",
    "분홍",
    "하늘색",
    "민트색",
    "청록색",
    "흰색",
    "검정색",
    "회색",
    "갈색",
    "베이지색",
    "안입음",
    "은색",
    "연두색",
    "자주색",
]

PANTY_COMMAND = re.compile(r"^!오늘의(.+)팬티색$")

COMMANDS = {
    "!도움말": (
        "사용 가능한 명령어: !공지 !통합공략 !단발퀘 !반복퀘 !멘테 "
        "!월간원정 !이벤트 !개구리야 !미르야\n"
        "추후 기능을 추가할 예정입니다."
    ),

    "!공지": (
        "https://kinggall.tistory.com/"
    ),

    "!통합공략": (
        "https://docs.google.com/spreadsheets/d/"
        "1prTM9Jg8TIvcV_UnhNA_2ccixNMS2fka/edit"
        "?gid=300604702#gid=300604702"
    ),

    "!단발퀘": (
        "https://docs.google.com/document/u/2/d/e/"
        "2PACX-1vQoYm6Rv1K5lHDcmZlIdLCrB9NliIR94gFuciicIsVLVrz7JoJAYsLFBL0Wroo8cSPczDoaJRMbt5Wf/pub"
    ),

    "!반복퀘": (
        "https://docs.google.com/document/d/e/"
        "2PACX-1vQTE6zVuatTYjaQosoy_wlxLgaCj_QK5SBgODuZEQEvT_fINDhGpeGrqPg72KqZDJ0JnYmjQZCZ5Z5e/pub"
    ),

    "!멘테": (
        "https://gall.dcinside.com/board/view/?id=kancolle_new1&no=979074"
    ),

    "!월간원정": (
        "https://docs.google.com/spreadsheets/d/e/"
        "2PACX-1vQrecPNerTyhxYFnL5hBh4ehbfetRkyD1twDM5jyJOp5ZQ6vW9fOTrJIdcg_HQmIHubay2ad-PbhB6g/pubhtml"
        "?gid=0&single=true"
    ),

    "!이벤트": (
        "현재 정기 이벤트 미정"
    ),

    "!개구리야": (
        "저의 전역일은 2026년 9월 24일입니다. 전역을 축하합니다!"
    ),

    "!미르야": (
        "저의 전역일은 2028년 4월 17일입니다"
    ),

    "안녕하세요": (
        "안녕하세요!"
    ),

    "ㅎㅇ": (
        "ㅎㅇㅎㅇ"
    ),

    "하이": (
        "하이하이"
    ),

    "안녕": (
        "반갑다"
    ),
}


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    message = str(data.get("msg", "")).strip()
    room = data.get("room", "")
    chat_id = data.get("json", {}).get("chat_id", room)

    print(f"[받은 메시지] 방={room}, 내용={message}")

    if message.startswith("!칸무스 "):
        arguments = message[len("!칸무스 "):].strip().split()
        keyword = arguments[0] if arguments else ""
        requested_stage = arguments[1] if len(arguments) > 1 else None
        results = search_ships(keyword)

        if not results:
            reply = f"'{keyword}' 칸무스를 찾지 못했습니다."
        else:
            reply = "\n\n".join(
                ship_text(ship, name_ko) for ship, name_ko in results
            )

        reply_data = {
            "type": "text",
            "room": str(chat_id),
            "data": reply
        }

        response = requests.post(
            IRIS_REPLY_URL,
            json=reply_data,
            timeout=10
        )

        print(f"[칸무스 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    panty_match = PANTY_COMMAND.fullmatch(message)

    if panty_match:
        character = panty_match.group(1)
        reply = random.choice(PANTY_COLORS)

        print(f"[오늘의 팬티색] 캐릭터={character}, 결과={reply}")

        reply_data = {
            "type": "text",
            "room": str(chat_id),
            "data": reply
        }

        response = requests.post(
            IRIS_REPLY_URL,
            json=reply_data,
            timeout=10
        )

        print(f"[답변 전송] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message in COMMANDS:
        reply = COMMANDS[message]

        reply_data = {
            "type": "text",
            "room": str(chat_id),
            "data": reply
        }

        response = requests.post(
            IRIS_REPLY_URL,
            json=reply_data,
            timeout=10
        )

        print(f"[답변 전송] 상태 코드={response.status_code}")

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def home():
    return "봇 서버가 실행 중입니다."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
