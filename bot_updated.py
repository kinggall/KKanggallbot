from flask import Flask, request, jsonify
import requests
import random
import re
import json
from pathlib import Path

app = Flask(__name__)

IRIS_REPLY_URL = "http://127.0.0.1:3000/reply"

DATA_DIR = Path(__file__).parent / "data"
SHIPS_FILE = DATA_DIR / "Ships.json"
SHIP_KO_FILE = DATA_DIR / "ship-ko.json"
SHIPS_URL = "https://raw.githubusercontent.com/ElectronicObserverEN/Data/master/Data/Ships.json"
SHIP_KO_URL = "https://raw.githubusercontent.com/ElectronicObserverEN/Data/master/Translations/ko-KR/ship.json"


def load_ship_data():
    """ElectronicObserver의 함선 목록과 한국어 번역을 한 번 내려받아 사용합니다."""
    DATA_DIR.mkdir(exist_ok=True)

    for url, path in ((SHIPS_URL, SHIPS_FILE), (SHIP_KO_URL, SHIP_KO_FILE)):
        if not path.exists():
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            path.write_bytes(response.content)

    with open(SHIPS_FILE, encoding="utf-8-sig") as file:
        ships = json.load(file)

    with open(SHIP_KO_FILE, encoding="utf-8-sig") as file:
        translations = json.load(file).get("ship", {})

    return ships, translations


try:
    SHIPS, SHIP_TRANSLATIONS = load_ship_data()
    print(f"[함선 데이터] {len(SHIPS)}개 로드 완료")
except Exception as error:
    SHIPS = []
    SHIP_TRANSLATIONS = {}
    print(f"[함선 데이터] 로드 실패: {error}")


def search_ships(keyword):
    keyword = keyword.strip().lower()
    results = []

    for ship in SHIPS:
        name_jp = str(ship.get("NameJP", ""))
        name_en = str(ship.get("NameEN", ""))
        name_ko = SHIP_TRANSLATIONS.get(name_jp, "")

        if keyword in {name_jp.lower(), name_en.lower(), name_ko.lower()}:
            results.append((ship, name_ko or name_jp))

    return results

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
        keyword = message[len("!칸무스 "):].strip()
        results = search_ships(keyword)

        if not results:
            reply = f"'{keyword}' 칸무스를 찾지 못했습니다."
        else:
            reply = "\n".join(
                f"{name_ko} ({ship.get('NameJP', '')}, {ship.get('NameEN', '')})"
                for ship, name_ko in results[:10]
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
