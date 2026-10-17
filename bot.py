from flask import Flask, request, jsonify
import requests
import random
import re
import json
import csv
import base64
import time
import os
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

app = Flask(__name__)

IRIS_REPLY_URL = "http://127.0.0.1:3000/reply"

CSV_FILE = Path(__file__).parent / "ships.csv"
SHIP_KO_FILE = Path(__file__).parent / "data" / "ship-ko.json"
SHIP_ALIASES_FILE = Path(__file__).parent / "data" / "ship_aliases.json"
SHIP_KO_URL = "https://raw.githubusercontent.com/kinggall/Data/master/Translations/ko-KR/ship.json"
SHIP_ALIASES_URL = "https://raw.githubusercontent.com/kinggall/KKanggallbot/main/data/ship_aliases.json"
SENKA_PAGE_URL = "https://senka.su/en"
SENKA_CACHE_SECONDS = 300
SENKA_RANKS = {"5", "20", "100", "500"}
SENKA_SERVER_NAMES = {
    1: "Yokosuka", 2: "Kure", 3: "Sasebo", 4: "Maizuru", 5: "Ominato",
    6: "Truk", 7: "Lingga", 8: "Rabaul", 9: "Shortland", 10: "Buin",
    11: "Tawi-Tawi", 12: "Palau", 13: "Brunei", 14: "Hitokappu",
    15: "Paramushir", 16: "Sukumo", 17: "Kanoya", 18: "Iwagawa",
    19: "Saiki", 20: "Hashirajima",
}
SENKA_CACHE = {"loaded_at": 0.0, "servers": None}

TSUNKIT_API = "https://tsunkit.net/api/routing"
TSUNKIT_CACHE_SECONDS = 12 * 60 * 60
TSUNKIT_CACHE_LOCK = threading.RLock()
TSUNKIT_CACHE = {}
DROP_REQUEST_TIMEOUT = 20
WIKI_LIMITED_DROPS_URL = (
    "https://wikiwiki.jp/kancolle/"
    "%E6%9C%9F%E9%96%93%E9%99%90%E5%AE%9A%E3%83%89%E3%83%AD%E3%83%83%E3%83%97%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88"
)


def get_local_cache_dir():
    """캐시를 저장소 밖에 둬 GitHub 자동 업데이트와 충돌하지 않게 합니다."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_dir = root / "KKanggallbot"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_dir = Path(tempfile.gettempdir()) / "KKanggallbot"
        cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


LOCAL_CACHE_DIR = get_local_cache_dir()
TSUNKIT_CACHE_FILE = LOCAL_CACHE_DIR / "tsunkit_cache.json"
LIMITED_DROPS_CACHE_FILE = LOCAL_CACHE_DIR / "current_limited_drops.json"


def load_tsunkit_cache():
    try:
        with open(TSUNKIT_CACHE_FILE, encoding="utf-8") as file:
            cache = json.load(file)
        if isinstance(cache, dict):
            return cache
    except (OSError, json.JSONDecodeError):
        pass
    return {}


TSUNKIT_CACHE.update(load_tsunkit_cache())


def save_tsunkit_cache():
    now = time.time()
    expired = [
        key for key, value in TSUNKIT_CACHE.items()
        if now - value.get("saved_at", 0) >= TSUNKIT_CACHE_SECONDS
    ]
    for key in expired:
        TSUNKIT_CACHE.pop(key, None)
    temporary_file = TSUNKIT_CACHE_FILE.with_suffix(".tmp")
    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(TSUNKIT_CACHE, file, ensure_ascii=False)
    temporary_file.replace(TSUNKIT_CACHE_FILE)


def get_tsunkit_json(path, params=None):
    """TsunKit 응답을 12시간 캐시하고, 봇 재시작 뒤에도 캐시를 재사용합니다."""
    params = params or {}
    cache_key = path + "?" + "&".join(
        f"{key}={params[key]}" for key in sorted(params)
    )
    now = time.time()
    with TSUNKIT_CACHE_LOCK:
        cached = TSUNKIT_CACHE.get(cache_key)
        if cached and now - cached.get("saved_at", 0) < TSUNKIT_CACHE_SECONDS:
            return cached["payload"]

    response = requests.get(
        f"{TSUNKIT_API}{path}",
        params=params,
        headers={"User-Agent": "Mozilla/5.0 KKanggallbot/1.0"},
        timeout=DROP_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError(f"TsunKit 응답 오류: {payload.get('error', '형식 오류')}")

    with TSUNKIT_CACHE_LOCK:
        TSUNKIT_CACHE[cache_key] = {"saved_at": now, "payload": payload}
        save_tsunkit_cache()
    return payload


class CurrentLimitedDropsParser(HTMLParser):
    """위키의 '현재 진행 중' 해역 요약표에서 해역별 함선 이름을 읽습니다."""

    TARGET_HEADING = "現在継続中の期間限定ドロップ艦"

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading_tag = None
        self.heading_text = []
        self.heading = ""
        self.waiting_for_table = False
        self.in_target_table = False
        self.finished = False
        self.in_row = False
        self.in_cell = False
        self.in_anchor = False
        self.cell_text = []
        self.anchor_text = []
        self.cell_anchors = []
        self.row_cells = []
        self.rows = []
        self.candidate_rows = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_tag = tag
            self.heading_text = []
        elif tag == "table" and self.waiting_for_table and not self.finished:
            self.in_target_table = True
            self.candidate_rows = []
        elif self.in_target_table and tag == "tr":
            self.in_row = True
            self.row_cells = []
        elif self.in_target_table and self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = []
            self.cell_anchors = []
        elif self.in_target_table and self.in_cell and tag == "a":
            self.in_anchor = True
            self.anchor_text = []

    def handle_data(self, data):
        if self.heading_tag:
            self.heading_text.append(data)
        if self.in_target_table and self.in_cell:
            self.cell_text.append(data)
            if self.in_anchor:
                self.anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading_tag and self.heading_tag:
            self.heading = " ".join("".join(self.heading_text).split())
            if tag == "h3" and self.TARGET_HEADING in self.heading:
                self.waiting_for_table = True
            self.heading_tag = None
            self.heading_text = []
        elif self.in_target_table and tag == "a" and self.in_anchor:
            anchor = " ".join("".join(self.anchor_text).split())
            if anchor:
                self.cell_anchors.append(anchor)
            self.in_anchor = False
            self.anchor_text = []
        elif self.in_target_table and self.in_cell and tag in ("td", "th"):
            text = " ".join("".join(self.cell_text).split())
            self.row_cells.append({"text": text, "links": self.cell_anchors[:]})
            self.in_cell = False
            self.cell_text = []
            self.cell_anchors = []
        elif self.in_target_table and tag == "tr" and self.in_row:
            self.candidate_rows.append(self.row_cells[:])
            self.in_row = False
            self.row_cells = []
        elif self.in_target_table and tag == "table":
            self.in_target_table = False
            if self.candidate_rows:
                header = {cell["text"] for cell in self.candidate_rows[0]}
                if {"海域", "エリア", "ドロップ対象"}.issubset(header):
                    self.rows = self.candidate_rows
                    self.finished = True
                    self.waiting_for_table = False


def parse_current_limited_drops(html_text):
    parser = CurrentLimitedDropsParser()
    parser.feed(html_text)
    if not parser.finished or len(parser.rows) < 2:
        raise ValueError("위키에서 현재 한정 드랍 요약표를 찾지 못했습니다.")

    maps = {}
    current_region = ""
    for row in parser.rows:
        cells = row
        if len(cells) < 2:
            continue
        header = [cell["text"] for cell in cells]
        if "エリア" in header or "ドロップ対象" in header:
            continue

        if len(cells) >= 3:
            if cells[0]["text"]:
                current_region = cells[0]["text"]
            map_text = cells[1]["text"]
            ship_cell = cells[2]
        else:
            map_text = cells[0]["text"]
            ship_cell = cells[1]

        map_match = re.search(r"(?<!\d)([1-7]-[1-6])(?!\d)", map_text)
        if not map_match:
            continue
        map_name = map_match.group(1)
        ship_names = ship_cell["links"]
        if not ship_names:
            ship_names = re.split(r"\s*[,、，;；]\s*", ship_cell["text"])
        ship_names = [name.strip() for name in ship_names if name.strip()]
        if ship_names:
            maps.setdefault(map_name, set()).update(ship_names)

    if not maps:
        raise ValueError("위키 요약표에서 해역별 함선 목록을 읽지 못했습니다.")
    return {map_name: sorted(names) for map_name, names in maps.items()}


def load_limited_drops_cache():
    try:
        with open(LIMITED_DROPS_CACHE_FILE, encoding="utf-8") as file:
            payload = json.load(file)
        maps = payload.get("maps")
        if isinstance(maps, dict):
            return payload
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {"updated_at": None, "maps": {}}


CURRENT_LIMITED_DROPS = load_limited_drops_cache()
if CURRENT_LIMITED_DROPS.get("updated_at"):
    print(
        "[한정 드랍 목록] 로컬 캐시 "
        f"{len(CURRENT_LIMITED_DROPS.get('maps', {}))}개 해역 로드 완료"
    )
else:
    print("[한정 드랍 목록] 아직 저장된 목록이 없습니다. 점검 후 !드랍갱신을 입력하세요.")


def refresh_current_limited_drops():
    response = requests.get(
        WIKI_LIMITED_DROPS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=30,
    )
    response.raise_for_status()
    maps = parse_current_limited_drops(response.text)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "maps": maps,
    }
    temporary_file = LIMITED_DROPS_CACHE_FILE.with_suffix(".tmp")
    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    temporary_file.replace(LIMITED_DROPS_CACHE_FILE)
    CURRENT_LIMITED_DROPS.clear()
    CURRENT_LIMITED_DROPS.update(payload)
    return len(maps), sum(len(names) for names in maps.values())


def tsunkit_date_range():
    now = datetime.now(timezone(timedelta(hours=9)))
    end_date = now.date()
    start_date = end_date - timedelta(days=180)
    return start_date.isoformat(), end_date.isoformat()


def tsunkit_map_names():
    payload = get_tsunkit_json("/maps/all/meta")
    maps = payload.get("result", {}).get("maps", {})
    return sorted(
        map_name for map_name in maps
        if re.fullmatch(r"[1-7]-[1-6]", map_name)
    )


def get_map_boss_edges(map_name):
    payload = get_tsunkit_json(f"/maps/{map_name}")
    route = payload.get("result", {}).get("route", {})
    return [
        str(edge_id) for edge_id, edge in route.items()
        if isinstance(edge, list) and len(edge) >= 3 and edge[2] == 5
    ]


def get_boss_drops(map_name):
    edges = get_map_boss_edges(map_name)
    if not edges:
        return []
    start_date, end_date = tsunkit_date_range()
    edge_path = ",".join(edges)
    payload = get_tsunkit_json(
        f"/maps/{map_name}/edges/{edge_path}/drops",
        {"start": start_date, "end": end_date, "ranks": "SA"},
    )
    result = payload.get("result", {})
    entries = result.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"TsunKit {map_name} 드랍 데이터 형식이 올바르지 않습니다.")
    return entries


def limited_drop_names(map_name):
    maps = CURRENT_LIMITED_DROPS.get("maps", {})
    return {
        normalize_ship_name(name)
        for name in maps.get(map_name, [])
    }


def drop_entry_is_limited(entry, map_name):
    current_names = limited_drop_names(map_name)
    entry_names = {
        normalize_ship_name(entry.get("name", "")),
        normalize_ship_name(entry.get("name_en", "")),
    }
    return bool(current_names.intersection(entry_names))


def filter_rare_and_limited_drops(entries, map_name):
    selected = []
    for entry in entries:
        if int(entry.get("id", 0) or 0) <= 0:
            continue
        limited = drop_entry_is_limited(entry, map_name)
        if limited or entry.get("rarity") == 1:
            selected.append({**entry, "limited": limited})
    selected.sort(key=lambda entry: float(entry.get("pct", 0) or 0), reverse=True)
    return selected


def drop_ship_display_name(entry):
    name_jp = str(entry.get("name", "")).strip()
    return SHIP_TRANSLATIONS.get(name_jp) or entry.get("name_en") or name_jp or "알 수 없는 함선"


def format_map_drops(map_name, entries):
    selected = filter_rare_and_limited_drops(entries, map_name)
    lines = [f"{map_name} 보스 드랍 (최근 6개월)"]
    if not selected:
        lines.append("레어/현재 한정 드랍 함선이 없습니다.")
    else:
        for entry in selected:
            count = int(entry.get("drops", 0) or 0)
            total = int(entry.get("total", 0) or 0)
            pct = float(entry.get("pct", 0) or 0)
            limited_mark = " (기간한정)" if entry["limited"] else ""
            lines.append(
                f"· {drop_ship_display_name(entry)} {pct:.2f}% "
                f"({count:,}/{total:,}){limited_mark}"
            )
    if not CURRENT_LIMITED_DROPS.get("updated_at"):
        lines.append("한정 목록 미등록: 점검 후 !드랍갱신을 입력하세요.")
    return "\n".join(lines)


def find_ship_boss_drops(keyword):
    ship_results = search_ships(keyword)
    ship_ids = {
        int(ship.get("艦船ID", 0) or 0)
        for ship, _ in ship_results
        if int(ship.get("艦船ID", 0) or 0) > 0
    }
    if not ship_ids:
        return None, []

    maps = tsunkit_map_names()
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(get_boss_drops, map_name): map_name for map_name in maps}
        for future in as_completed(futures):
            map_name = futures[future]
            try:
                for entry in future.result():
                    if int(entry.get("id", 0) or 0) in ship_ids:
                        results.append({
                            **entry,
                            "map_name": map_name,
                            "limited": drop_entry_is_limited(entry, map_name),
                        })
            except Exception as error:
                print(f"[드랍 검색 일부 실패] 해역={map_name}, 오류={error}")
                errors.append(map_name)
    results.sort(key=lambda entry: float(entry.get("pct", 0) or 0), reverse=True)
    return errors, results


def format_ship_drops(keyword, errors, entries):
    if not entries and not errors:
        return f"'{keyword}'의 보스 드랍 기록을 찾지 못했습니다."
    by_map = {}
    for entry in entries:
        map_name = entry["map_name"]
        group = by_map.setdefault(map_name, {
            "drops": 0,
            "total": 0,
            "limited": False,
        })
        group["drops"] += int(entry.get("drops", 0) or 0)
        group["total"] = max(group["total"], int(entry.get("total", 0) or 0))
        group["limited"] = group["limited"] or entry["limited"]

    ranked_maps = []
    for map_name, group in by_map.items():
        if group["total"]:
            group["map_name"] = map_name
            group["pct"] = group["drops"] / group["total"] * 100
            ranked_maps.append(group)
    ranked_maps.sort(key=lambda entry: entry["pct"], reverse=True)

    lines = [f"{keyword} 보스 드랍률 상위 5개 (최근 6개월)"]
    for entry in ranked_maps[:5]:
        pct = float(entry.get("pct", 0) or 0)
        count = int(entry.get("drops", 0) or 0)
        total = int(entry.get("total", 0) or 0)
        limited_mark = " (기간한정)" if entry["limited"] else ""
        lines.append(
            f"· {entry['map_name']} {pct:.2f}% ({count:,}/{total:,}){limited_mark}"
        )
    if errors:
        lines.append("일부 해역 데이터 조회에 실패해 결과가 불완전할 수 있습니다.")
    if not CURRENT_LIMITED_DROPS.get("updated_at"):
        lines.append("한정 목록 미등록: 점검 후 !드랍갱신을 입력하세요.")
    return "\n".join(lines)


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

def load_ship_aliases():
    try:
        response = requests.get(SHIP_ALIASES_URL, timeout=15)
        response.raise_for_status()
        aliases = response.json()
        if not isinstance(aliases, dict):
            raise ValueError("GitHub 별명 파일의 최상위 형식이 객체가 아닙니다.")

        # 저장소 파일은 수정하지 않습니다. 실행 중 로컬 Git 변경이 생기면
        # 감시 스크립트가 다음 GitHub 업데이트를 가져오지 못할 수 있습니다.
        print(f"[함선 별명] GitHub에서 최신 {len(aliases)}개 함선 별명 읽기 완료")
        return aliases
    except Exception as error:
        try:
            with open(SHIP_ALIASES_FILE, encoding="utf-8") as file:
                aliases = json.load(file)
            print(f"[함선 별명] GitHub 동기화 실패, 로컬 캐시 {len(aliases)}개 사용: {error}")
            return aliases
        except Exception as cache_error:
            print(f"[함선 별명] GitHub·로컬 파일 로드 실패: {error}; {cache_error}")
            return {}


SHIP_ALIASES = load_ship_aliases()


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
            0: "특무함", 1: "등대보급선", 2: "남극관측선"
        },
        "日進": {
            0: "미개장", 1: "개1", 2: "갑"
        },
        "Glorious": {
            0: "미개장", 1: "항모", 2: "개1(정규항모)", 3: "개1(순양전함)"
        },
        "Glorious改": {
            2: "개1(정규항모)", 3: "개1(순양전함)"
        },
    }
    labels = special_stages.get(name)
    if labels is None:
        # 개장 후 이름이 千歳改·千歳甲처럼 바뀌는 계보도
        # 미개장 함선의 특수 표기 규칙을 공유합니다.
        for special_name, candidate_labels in special_stages.items():
            if name.startswith(special_name):
                labels = candidate_labels
                break
    if labels is not None and stage in labels:
        return labels[stage]
    if stage == 0:
        return "미개장"

    # 해외함과 함종 변경 함선 중, 改二처럼 단계 표기가 아니라
    # 고유한 이름으로 개장 상태를 구분하는 경우입니다.
    named_stages = {
        "Bismarck改": "개1",
        "Bismarck zwei": "즈바이",
        "Bismarck drei": "드라이",
        "Верный": "베르니",
        "呂500": "로-500",
        "Zara due": "두에",
        "Гангут два": "드바",
        "Gotland andra": "안드라",
        "丹陽": "단양",
        "UIT-25": "UIT-25",
        "UIT-24": "UIT-24",
        "伊504": "이504",
        "伊503": "이503",
        "General Belgrano": "제너럴 벨그라노",
        "Richelieu Deux": "Deux",
        "Conte di Cavour nuovo": "nuovo",
        "Leonardo da Vinci": "레오나르도 다 빈치",
        "Independence Flight II": "Flight II",
        "Bearn amelioration": "개량형",
    }
    if name in named_stages:
        return named_stages[name]

    # 개장 단계 숫자 대신 함선의 실제 개장 명칭을 우선 표시합니다.
    # 예: 鈴谷航改二 -> 개2항, 三隈改二特 -> 개2특
    remodel_tokens = (
        ("改三護", "개3호"),
        ("航改二", "개2항"),
        ("改二特", "개2특"),
        ("改二丁", "개2정"),
        ("改二乙", "개2을"),
        ("改二丙", "개2병"),
        ("改二戊", "개2무"),
        ("改二護", "개2호"),
        ("改二補", "개2보"),
        ("改二戦", "개2전"),
        ("改二重", "개2중"),
        ("改二甲", "개2갑"),
        ("改二", "개2"),
        ("改三", "개3"),
        ("乙改", "을개"),
        ("丁改", "정개"),
        ("改母", "개모"),
    )
    for token, label in remodel_tokens:
        if token in name:
            return label
    if "Mk.II Mod.2" in name:
        return "Mk.II Mod.2"
    if "改 Mod.2" in name:
        return "개2 Mod.2"
    if "Mk.II" in name:
        return "Mk.II"
    return f"개{stage}"


def ship_text(ship, name_ko):
    stage = ship_stage(ship)
    current_stage = int(ship.get("改装段階", "0") or 0)
    next_ship_name = ship.get("改装後", "-")
    next_level = ship.get("改装Lv", "-")

    result = [
        f"[{stage}]",
        f"화력 {ship.get('火力最大', '-')} / 뇌장 {ship.get('雷装最大', '-')} / "
        f"대공 {ship.get('対空最大', '-')} / 장갑 {ship.get('装甲最大', '-')}"
    ]
    if next_ship_name not in ("", "-") and next_level not in ("", "0", "-"):
        next_candidates = [
            candidate for candidate in SHIPS
            if candidate.get("艦名") == next_ship_name
            and int(candidate.get("改装段階", "0") or 0) > current_stage
        ]
        next_candidate = min(
            next_candidates,
            key=lambda candidate: int(candidate.get("改装段階", "0") or 0),
            default=None,
        )
        next_stage = ship_stage(next_candidate) if next_candidate else "컨버트"
        result.append(f"{next_stage} 개장 레벨: {next_level}")
    return "\n".join(result)


def load_senka_data():
    """Senka Viewer 첫 페이지에 포함된 공개 서버별 랭킹 데이터를 읽습니다."""
    if SENKA_CACHE["servers"] and time.monotonic() - SENKA_CACHE["loaded_at"] < SENKA_CACHE_SECONDS:
        return SENKA_CACHE["servers"]

    response = requests.get(
        SENKA_PAGE_URL,
        headers={"User-Agent": "Mozilla/5.0 KKanggallbot/1.0"},
        timeout=15,
    )
    response.raise_for_status()

    next_data_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        response.text,
        flags=re.DOTALL,
    )
    if not next_data_match:
        raise ValueError("Senka 페이지에서 데이터 영역을 찾지 못했습니다.")

    next_data = json.loads(next_data_match.group(1))
    encoded_data = next_data["props"]["pageProps"]["b64data"]
    decoded_data = json.loads(base64.b64decode(encoded_data))
    servers = decoded_data.get("server_list")
    if not isinstance(servers, list) or not servers:
        raise ValueError("Senka 서버 목록이 비어 있거나 형식이 바뀌었습니다.")

    # 누락되거나 잘못된 데이터가 있으면 조용히 잘못된 순위를 표시하지 않습니다.
    for server in servers:
        server_number = int(server["servernum"])
        cutoff = server["cutoff"]
        if not 1 <= server_number <= 20 or not isinstance(cutoff, dict):
            raise ValueError("Senka 서버 데이터 형식이 올바르지 않습니다.")
        for rank in SENKA_RANKS:
            if rank not in cutoff:
                raise ValueError(f"Senka 서버 {server_number}의 Top {rank} 데이터가 없습니다.")

    servers.sort(key=lambda server: int(server["servernum"]))
    SENKA_CACHE["servers"] = servers
    SENKA_CACHE["loaded_at"] = time.monotonic()
    return servers


def format_senka_ranking(rank):
    servers = load_senka_data()
    lines = [f"Senka 전과 Top {rank}"]
    for server in servers:
        number = int(server["servernum"])
        name = SENKA_SERVER_NAMES.get(number, f"Server {number}")
        value = server["cutoff"][str(rank)]
        stale_mark = "(미갱신)" if senka_is_stale(server["lastmodifided"]) else ""
        lines.append(f"{number:02d} {name}: {value}{stale_mark}")
    return "\n".join(lines)


def senka_is_stale(last_modified_ms, now=None):
    """Senka 사이트와 같은 기준으로 예정 갱신 시각이 12시간 지난 서버를 표시합니다."""
    modified = datetime.fromtimestamp(int(last_modified_ms) / 1000, tz=timezone.utc)
    hour = modified.hour
    if 6 <= hour < 18:
        update_boundary = modified.replace(hour=6, minute=0, second=0, microsecond=0)
    else:
        update_boundary = modified.replace(hour=18, minute=0, second=0, microsecond=0)
        if hour < 6:
            update_boundary -= timedelta(days=1)

    current_time = now or datetime.now(timezone.utc)
    return current_time - update_boundary >= timedelta(hours=12)

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
    "금색",
    "연보라색",
    "진보라색",
    "연분홍색",
    "진분홍색",
    "연파랑색",
    "진파랑색",
    "연노랑색",
    "진노랑색",
    "연주황색",
    "진주황색",
    "연초록색",
    "진초록색",
    "연갈색",
    "진갈색",
    "아이보리색",
    "살구색",
    "와인색",
    "청색",
    "형광색",
]

PANTY_COMMAND = re.compile(r"^!(.+)팬티색$")

COMMANDS = {
    "!도움말": (
        "사용 가능한 명령어:\n"
        "!공지 !통합공략 !단발퀘 !반복퀘 !멘테 !월간원정\n"
        "!이벤트 !개구리야 !미르야\n"
        "!전과 [5/20/100/500]\n"
        "!드랍 [해역/함선명]  |  점검 후 !드랍갱신\n"
        "!칸무스 [함선명]\n"
        "![함선명]팬티색"
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

    if message == "!드랍갱신":
        try:
            map_count, ship_count = refresh_current_limited_drops()
            updated = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
            reply = (
                f"현재 한정 드랍 목록 갱신 완료 ({map_count}개 해역, "
                f"{ship_count}개 함선)\n갱신 시각: {updated}"
            )
            print(f"[한정 드랍 목록] {map_count}개 해역 갱신")
        except Exception as error:
            print(f"[한정 드랍 목록 갱신 실패] {error}")
            reply = "한정 드랍 목록을 갱신하지 못했습니다. 기존 목록은 유지합니다."

        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[드랍 목록 갱신 답변] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!드랍" or message.startswith("!드랍 "):
        query = message[len("!드랍"):].strip()
        if not query:
            reply = "사용법: !드랍 5-5 또는 !드랍 함선명"
        elif re.fullmatch(r"[1-7]-[1-6]", query):
            try:
                reply = format_map_drops(query, get_boss_drops(query))
            except Exception as error:
                print(f"[해역 드랍 조회 실패] 해역={query}, 오류={error}")
                reply = f"{query} 보스 드랍 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
        else:
            try:
                errors, entries = find_ship_boss_drops(query)
                if errors is None:
                    reply = f"'{query}' 칸무스를 찾지 못했습니다."
                else:
                    reply = format_ship_drops(query, errors, entries)
            except Exception as error:
                print(f"[함선 드랍 검색 실패] 함선={query}, 오류={error}")
                reply = "함선 드랍 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."

        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[드랍 조회 답변] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message.startswith("!전과"):
        arguments = message.split()
        if len(arguments) != 2 or arguments[0] != "!전과" or arguments[1] not in SENKA_RANKS:
            reply = "사용법: !전과 5 / !전과 20 / !전과 100 / !전과 500"
        else:
            try:
                reply = format_senka_ranking(arguments[1])
            except Exception as error:
                print(f"[랭킹컷 조회 실패] {error}")
                reply = "랭킹컷 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."

        reply_data = {
            "type": "text",
            "room": str(chat_id),
            "data": reply
        }
        response = requests.post(IRIS_REPLY_URL, json=reply_data, timeout=10)
        print(f"[전과 답변] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

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
