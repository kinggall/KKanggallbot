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
import fit_bonus
import equipment_lookup
import development
import initial_equipment
import improvement
import remodel_materials
import kanlog_drops

app = Flask(__name__)

IRIS_REPLY_URL = "http://127.0.0.1:3000/reply"

CSV_FILE = Path(__file__).parent / "ships.csv"
SHIP_KO_FILE = Path(__file__).parent / "data" / "ship-ko.json"
SHIP_ALIASES_FILE = Path(__file__).parent / "data" / "ship_aliases.json"
SHIP_AIRCRAFT_RULES_FILE = Path(__file__).parent / "data" / "ship_aircraft_rules.json"
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
BOSS_NODES_BY_STAGE = {
    "5-6": ("G", "N", "Z"),
    "7-2": ("G", "M"),
    "7-3": ("E", "P"),
    "7-5": ("K", "Q", "T"),
}
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
KANLOG_DROPS = kanlog_drops.DropStore(LOCAL_CACHE_DIR)
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

    for attempt in range(3):
        try:
            response = requests.get(
                f"{TSUNKIT_API}{path}", params=params,
                headers={"User-Agent": "Mozilla/5.0 KKanggallbot/1.0"},
                timeout=DROP_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("TsunKit 데이터 응답이 올바르지 않습니다.")
            break
        except (requests.RequestException, ValueError) as error:
            if attempt == 2:
                raise
            print(f"[TsunKit 재시도] 경로={path}, 회차={attempt + 1}, 오류={error}")
            time.sleep(0.5 * (attempt + 1))

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
        self.tooltips = []
        self.anchor_tooltip = None

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
            self.anchor_tooltip = dict(attrs).get("data-tooltip-content")

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
                if self.anchor_tooltip:
                    self.tooltips.append((anchor, self.anchor_tooltip))
            self.anchor_tooltip = None
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


class WikiNode:
    def __init__(self, tag="", attrs=None, deleted=False):
        self.tag = tag
        self.attrs = dict(attrs or [])
        style = self.attrs.get("style", "").replace(" ", "").lower()
        self.deleted = deleted or tag in ("del", "s", "strike") or "line-through" in style
        self.children = []
        self.parent = None

    def text(self, include_deleted=False):
        if self.deleted and not include_deleted:
            return ""
        if self.tag == "br":
            return "\n"
        return "".join(child if isinstance(child, str) else child.text(include_deleted)
                       for child in self.children)

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, WikiNode):
                yield from child.walk(tag)


class WikiDocumentParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = WikiNode()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = WikiNode(tag, attrs, self.stack[-1].deleted)
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def wiki_table_grid(table):
    """rowspan/colspan이 있는 오래된 표도 열 위치를 유지합니다."""
    spans = {}
    grid = []
    for tr in table.walk("tr"):
        row = {column: cell for column, (_, cell) in spans.items()}
        spans = {column: (remaining - 1, cell)
                 for column, (remaining, cell) in spans.items() if remaining > 1}
        column = 0
        for cell in tr.children:
            if not isinstance(cell, WikiNode) or cell.tag not in ("td", "th"):
                continue
            while column in row:
                column += 1
            width = int(cell.attrs.get("colspan", "1"))
            height = int(cell.attrs.get("rowspan", "1"))
            for offset in range(width):
                row[column + offset] = cell
                if height > 1:
                    spans[column + offset] = (height - 1, cell)
            column += width
        if row:
            grid.append([row.get(i) for i in range(max(row) + 1)])
    return grid


def parse_event_drop_locations(html_text):
    """점검별 본문이 우선: 일부 계속 중도 포함하고 취소선은 함선별로 제외합니다."""
    document = WikiDocumentParser()
    document.feed(html_text)
    title = ""
    ongoing = False
    ended_section = False
    locations = {}
    for element in document.root.walk():
        if element.tag == "h2":
            title = " ".join(element.text(include_deleted=True).split())
            ongoing = "継続中" in title and not element.deleted
            ended_section = not ongoing and "終了" in title
        if element.tag != "table" or not (ongoing or ended_section):
            continue
        grid = wiki_table_grid(element)
        if not grid:
            continue
        headers = [re.sub(r"\s+", "", c.text(True)) if c else "" for c in grid[0]]
        map_column = next((i for i, h in enumerate(headers) if h in ("エリア", "ポイント", "ドロップエリア")), None)
        ship_column = next((i for i, h in enumerate(headers) if "ドロップ対象" in h), None)
        if map_column is None:
            continue
        # 一部の古い表は見出し側に艦名を持ち、エリア列しか持ちません。
        title_names = []
        permanent_context = ""
        if ship_column is None:
            branch = element
            while branch.parent is not None:
                parent = branch.parent
                if parent.tag == "li":
                    prefix = parent.children[:parent.children.index(branch)]
                    links = [a for child in prefix if isinstance(child, WikiNode)
                             for a in child.walk("a") if a.text(True).strip()]
                    if links:
                        title_names = [(a.text(True).strip(), a.deleted) for a in links]
                        tail = parent.children[parent.children.index(branch) + 1:]
                        permanent_context = "".join(child if isinstance(child, str) else child.text()
                                                    for child in tail)
                        break
                branch = parent
            if not title_names:
                title_names = [(a.text(True).strip(), a.deleted)
                               for a in element_title_links(document.root, title)
                               if a.text(True).strip() and not a.text(True).strip().startswith("*")]
        for row in grid[1:]:
            if map_column >= len(row) or row[map_column] is None:
                continue
            map_cell = row[map_column]
            spots = list(wiki_drop_spots(map_cell.text(True)))
            if not spots:
                for map_name in re.findall(r"([1-7]-[1-6])\s*[（(]全域[)）]", map_cell.text(True)):
                    spots.append((map_name, "*"))
                for map_name in re.findall(r"([1-7]-[1-6])\s*ボス", map_cell.text(True)):
                    spots.append((map_name, "*"))
            if not spots:
                continue
            if ship_column is not None:
                if ship_column >= len(row) or row[ship_column] is None:
                    continue
                ship_cell = row[ship_column]
                links = [a for a in ship_cell.walk("a")
                         if a.text(True).strip() and not a.text(True).strip().startswith("*")]
                names = [(a.text(True).strip(), a.deleted) for a in links]
                if not names:
                    names = [(name.strip(), ship_cell.deleted)
                             for name in re.split(r"[,、，\n]", ship_cell.text(True)) if name.strip()]
                context = ship_cell.text(True)
            else:
                names = title_names
                context = title
            for name, struck in names:
                explicit_end = bool(re.search(re.escape(name) + r"\s*[（(]終了[)）]", context + title))
                ended = struck or map_cell.deleted or ended_section or explicit_end
                for map_name, node in spots:
                    key = (name, map_name, node, ended)
                    locations[key] = {"name": name, "map": map_name, "node": node,
                                      "limited": not ended, "ended": ended,
                                      "event_title": title}
        if title_names and re.search(r"平時にも|常設|恒常", permanent_context):
            for map_name, node in wiki_drop_spots(permanent_context):
                for name, struck in title_names:
                    if not struck:
                        locations[(name, map_name, node, "permanent")] = {
                            "name": name, "map": map_name, "node": node,
                            "limited": False, "ended": False, "event_title": title}
    if not any(record["limited"] for record in locations.values()):
        raise ValueError("점검별 본문에서 진행 중인 드랍 표를 읽지 못했습니다.")
    return list(locations.values())


def element_title_links(root, title):
    for heading in root.walk("h2"):
        if " ".join(heading.text(True).split()) == title:
            return list(heading.walk("a"))
    return []


def parse_current_limited_drops(html_text):
    maps = {}
    for record in parse_event_drop_locations(html_text):
        if record["limited"]:
            maps.setdefault(record["map"], set()).add(record["name"])
    return {map_name: sorted(names) for map_name, names in maps.items()}


def wiki_drop_spots(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.translate(str.maketrans({c: "-" for c in "ｰー−‐–—"}))
    for match in re.finditer(
        r"([1-7]-[1-6])-([A-Z]+\d*(?:\s*[,、]\s*[A-Z]+\d*)*)", text
    ):
        for node in re.split(r"\s*[,、]\s*", match.group(2)):
            yield match.group(1), node




def load_limited_drops_cache():
    try:
        with open(LIMITED_DROPS_CACHE_FILE, encoding="utf-8") as file:
            payload = json.load(file)
        maps = payload.get("maps")
        if isinstance(maps, dict) and payload.get("schema_version") == 3:
            return payload
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {"updated_at": None, "maps": {}}


def parse_limited_drop_locations(html_text):
    """한정/종료는 점검 본문, 명시된 상시 참고 위치만 상단 툴팁에서 읽습니다."""
    parser = CurrentLimitedDropsParser()
    parser.feed(html_text)
    locations = parse_event_drop_locations(html_text)
    for name, tooltip in parser.tooltips:
        _, _, permanent_text = tooltip.partition("※")
        if not re.search(r"常設|恒常", permanent_text):
            continue
        for map_name, node in wiki_drop_spots(permanent_text):
            record = {"name": name, "map": map_name, "node": node, "limited": False}
            if record not in locations:
                locations.append(record)
    if not locations:
        raise ValueError("현재 한정 드랍의 노드 정보를 찾지 못했습니다.")
    return locations


CURRENT_LIMITED_DROPS = load_limited_drops_cache()


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
    locations = parse_limited_drop_locations(response.text)
    payload = {
        "schema_version": 3,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "maps": maps,
        "locations": locations,
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
    result = payload.get("result")
    maps = result.get("maps") if isinstance(result, dict) else None
    if not isinstance(maps, (dict, list)) or not maps:
        raise ValueError("TsunKit 해역 목록을 읽지 못했습니다.")
    return sorted(
        map_name for map_name in maps
        if re.fullmatch(r"[1-7]-[1-6]", map_name)
    )


def get_map_boss_groups(map_name):
    payload = get_tsunkit_json(f"/maps/{map_name}")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("route"), dict):
        raise ValueError(f"{map_name} 지도 데이터를 읽지 못했습니다.")
    route = result["route"]
    nodes = {edge[1] for edge in route.values()
             if isinstance(edge, list) and len(edge) >= 3 and edge[2] == 5}
    ordered = BOSS_NODES_BY_STAGE.get(map_name)
    if ordered:
        if set(ordered) != nodes:
            raise ValueError(f"{map_name} 보스 구성이 변경되어 재확인이 필요합니다.")
    elif len(nodes) > 1:
        raise ValueError(f"{map_name}의 최종보스 노드 확인이 필요합니다.")
    else:
        ordered = sorted(nodes)
    return [(node, [str(key) for key, edge in route.items() if edge[1] == node])
            for node in ordered]


def get_map_boss_edges(map_name, stage=None):
    groups = get_map_boss_groups(map_name)
    if not groups:
        return []
    if stage is not None and not 1 <= stage <= len(groups):
        raise ValueError(f"{map_name}은 {len(groups)}개 보스가 있습니다.")
    return groups[-1 if stage is None else stage - 1][1]


def get_boss_drops(map_name, stage=None):
    groups = get_map_boss_groups(map_name)
    if not groups:
        return []
    if stage is not None and not 1 <= stage <= len(groups):
        raise ValueError(f"{map_name}은 {len(groups)}개 보스가 있습니다.")
    stage_number = len(groups) if stage is None else stage
    node, edges = groups[stage_number - 1]
    start_date, end_date = tsunkit_date_range()
    edge_path = ",".join(edges)
    payload = get_tsunkit_json(
        f"/maps/{map_name}/edges/{edge_path}/drops",
        {"start": start_date, "end": end_date, "ranks": "SA"},
    )
    result = payload.get("result")
    entries = result.get("entries") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"TsunKit {map_name} 드랍 데이터 형식이 올바르지 않습니다.")
    return [{**entry, "node": node, "boss_stage": stage_number,
             "boss_count": len(groups), "map_name": map_name} for entry in entries]


def get_all_boss_drops(map_name):
    entries = []
    for stage in range(1, len(get_map_boss_groups(map_name)) + 1):
        entries.extend(get_boss_drops(map_name, stage))
    return entries


def limited_drop_names(map_name):
    maps = CURRENT_LIMITED_DROPS.get("maps", {})
    return {
        normalize_ship_name(name)
        for name in maps.get(map_name, [])
    }


def drop_entry_status(entry, map_name):
    entry_names = {
        normalize_ship_name(entry.get("name", "")),
        normalize_ship_name(entry.get("name_en", "")),
    }
    entry_names.update(DROP_SHIP_NAMES.get(int(entry.get("id", 0) or 0), set()))
    node = entry.get("node")
    records = [record for record in CURRENT_LIMITED_DROPS.get("locations", [])
               if record["map"] == map_name
               and normalize_ship_name(record["name"]) in entry_names]
    exact = [record for record in records if record["node"] in (node, "*")]
    if any(record["limited"] for record in exact):
        return "limited"
    if any(not record.get("ended") and not record["limited"] for record in exact):
        return "permanent"
    if any(record.get("ended") for record in exact):
        return "ended"
    if not records and limited_drop_names(map_name).intersection(entry_names):
        return "unverified"
    # Exclusive 분류만으로 종료/상시를 단정할 수 없습니다.
    # 현재 위치 근거가 없으면 미확인으로 두고 현재 목록에서는 제외합니다.
    if entry.get("rarity") == 2:
        return "unconfirmed"
    return "permanent"


def drop_entry_is_limited(entry, map_name):
    return drop_entry_status(entry, map_name) == "limited"


def drop_rate_value(entry):
    total = int(entry.get("total", 0) or 0)
    if total > 0:
        return int(entry.get("drops", 0) or 0) / total * 100
    return float(entry.get("pct", 0) or 0)


def format_drop_rate(entry):
    value = drop_rate_value(entry)
    if 0 < value < 0.01:
        return "<0.01%"
    return f"{value:.2f}%"


def filter_rare_and_limited_drops(entries, map_name):
    selected = []
    for entry in entries:
        if int(entry.get("id", 0) or 0) <= 0:
            continue
        status = drop_entry_status(entry, map_name)
        if status in ("limited", "unverified") or (
            status == "permanent" and entry.get("rarity") in (1, 2)
        ):
            selected.append({**entry, "limited": status == "limited", "drop_status": status})
    selected.sort(key=lambda entry: (-drop_rate_value(entry), int(entry.get("id", 0) or 0)))
    return selected


def drop_ship_display_name(entry):
    name_jp = str(entry.get("name", "")).strip()
    translated = SHIP_TRANSLATIONS.get(name_jp)
    if translated:
        return translated
    ship = SHIP_BY_GAME_ID.get(int(entry.get("id", 0) or 0), {})
    canonical = ship.get("艦名", name_jp)
    translated = SHIP_TRANSLATIONS.get(canonical)
    if translated:
        return translated
    for alias in SHIP_ALIASES.get(canonical, []):
        if re.search(r"[가-힣]", alias):
            return alias
    return entry.get("name_en") or name_jp or "알 수 없는 함선"


def format_map_drops(map_name, entries):
    selected = filter_rare_and_limited_drops(entries, map_name)
    if entries:
        first = entries[0]
        stage = f"-{first['boss_stage']}" if first.get("boss_count", 1) > 1 else ""
        location = f"{map_name}{stage}"
    else:
        location = map_name
    lines = [f"{location} Boss Drop (S/A · 최근 180일)"]
    if not selected:
        lines.append("레어/현재 한정 드랍 함선이 없습니다.")
    else:
        for entry in selected:
            rate = format_drop_rate(entry)
            limited_mark = " (기간한정)" if entry["limited"] else (
                " (한정 위치 미확인)" if entry["drop_status"] == "unverified" else "")
            lines.append(f"· {drop_ship_display_name(entry)} {rate}{limited_mark}")
    if not CURRENT_LIMITED_DROPS.get("updated_at"):
        lines.append("※ 한정 드랍 정보 미등록")
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
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(get_all_boss_drops, map_name): map_name for map_name in maps}
        for future in as_completed(futures):
            map_name = futures[future]
            try:
                for entry in future.result():
                    status = drop_entry_status(entry, map_name)
                    if int(entry.get("id", 0) or 0) in ship_ids and status not in ("unconfirmed", "ended"):
                        results.append({
                            **entry,
                            "map_name": map_name,
                            "limited": status == "limited",
                            "drop_status": status,
                        })
            except Exception as error:
                print(f"[드랍 검색 일부 실패] 해역={map_name}, 오류={error}")
                errors.append(map_name)
    results.sort(key=lambda entry: float(entry.get("pct", 0) or 0), reverse=True)
    return errors, results


def format_ship_drops(keyword, errors, entries):
    if errors:
        raise ValueError("드랍 자료를 모두 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
    if not entries and not errors:
        return f"'{keyword}'의 보스 드랍 기록을 찾지 못했습니다."
    by_map = {}
    for entry in entries:
        map_name = entry["map_name"]
        key = (map_name, entry.get("node"), entry.get("drop_status", "permanent"))
        group = by_map.setdefault(key, {
            "drops": 0,
            "total": 0,
            "limited": False,
            "map_name": map_name,
            "node": entry.get("node", "?"),
            "drop_status": entry.get("drop_status", "permanent"),
            "boss_count": entry.get("boss_count", 1),
            "boss_stage": entry.get("boss_stage", 1),
        })
        total = int(entry.get("total", 0) or 0)
        if group["total"] and total != group["total"]:
            raise ValueError("동일 노드의 표본 수가 달라 확률을 합산할 수 없습니다.")
        group["drops"] += int(entry.get("drops", 0) or 0)
        group["total"] = total
        group["limited"] = group["limited"] or entry["limited"]

    ranked_maps = []
    for group in by_map.values():
        if group["total"]:
            group["pct"] = group["drops"] / group["total"] * 100
            ranked_maps.append(group)
    ranked_maps.sort(key=lambda entry: (-entry["pct"], entry["map_name"], entry["node"]))

    chosen = ranked_maps[:5]
    lines = [f"{keyword} Boss Drop Top 5 (S/A · 최근 180일)"]

    def append_location(entry):
        rate = format_drop_rate(entry)
        limited_mark = " (기간한정)" if entry["limited"] else (
            " (한정 위치 미확인)" if entry["drop_status"] == "unverified" else "")
        stage = f"-{entry['boss_stage']}" if entry["boss_count"] > 1 else ""
        lines.append(f"· {entry['map_name']}{stage} {rate}{limited_mark}")

    for entry in chosen:
        append_location(entry)
    # 상위 5개의 순위는 유지하며, 반대 종류가 있을 때만 별도 참고로 제공합니다.
    for status, heading in (("limited", "추가 기간한정 드랍"), ("permanent", "추가 일반 드랍")):
        if not any(entry["drop_status"] == status for entry in chosen):
            other = next((entry for entry in ranked_maps if entry["drop_status"] == status), None)
            if other:
                lines.append(heading)
                append_location(other)
    if not CURRENT_LIMITED_DROPS.get("updated_at"):
        lines.append("※ 한정 드랍 정보 미등록")
    return "\n".join(lines)


def build_drop_reply(message):
    if message == "!드랍갱신":
        map_count, ship_count = refresh_current_limited_drops()
        updated = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
        return (f"현재 한정 드랍 목록 갱신 완료 ({map_count}개 해역, "
                f"{ship_count}개 함선)\n갱신 시각: {updated}")
    query = message[len("!드랍"):].strip()
    if not query:
        return "사용법: !드랍 [해역] / !드랍 [함선명]\n예: !드랍 55p / !드랍 후부키"
    match = re.fullmatch(r"([1-7]-[1-6])(?:-([1-3]))?", query)
    if match:
        map_name, stage = match.groups()
        entries = get_boss_drops(map_name, int(stage) if stage else None)
        if not entries and not get_map_boss_groups(map_name):
            return "보스방이 존재하지 않습니다."
        return format_map_drops(map_name, entries)
    errors, entries = find_ship_boss_drops(query)
    if errors is None:
        return f"'{query}' 칸무스를 찾지 못했습니다."
    return format_ship_drops(query, errors, entries)


def send_drop_reply(message, chat_id):
    """전체 해역 조회가 길어져도 Iris의 webhook 요청은 즉시 마칠 수 있게 합니다."""
    try:
        reply = build_drop_reply(message)
    except Exception as error:
        print(f"[드랍 처리 실패] 명령={message}, 오류={error}")
        if message == "!드랍갱신":
            reply = "한정 드랍 목록을 갱신하지 못했습니다. 기존 목록은 유지합니다."
        elif isinstance(error, ValueError):
            reply = str(error)
        else:
            reply = "드랍 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
    try:
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        response.raise_for_status()
        print(f"[드랍 답변] 상태 코드={response.status_code}")
    except requests.RequestException as error:
        print(f"[드랍 답변 전송 실패] {error}")


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
        with open(SHIP_ALIASES_FILE, encoding="utf-8") as file:
            aliases = json.load(file)
        if not isinstance(aliases, dict):
            raise ValueError("로컬 별명 파일의 최상위 형식이 객체가 아닙니다.")
        print(f"[함선 별명] 로컬 파일에서 {len(aliases)}개 함선 별명 읽기 완료")
        return aliases
    except Exception as local_error:
        print(f"[함선 별명] 로컬 파일 로드 실패, GitHub에서 가져옵니다: {local_error}")
    try:
        response = requests.get(SHIP_ALIASES_URL, timeout=15)
        response.raise_for_status()
        aliases = response.json()
        if not isinstance(aliases, dict):
            raise ValueError("GitHub 별명 파일의 최상위 형식이 객체가 아닙니다.")

        # 저장소 파일은 수정하지 않습니다. 실행 중 로컬 Git 변경이 생기면
        # 감시 스크립트가 다음 GitHub 업데이트를 가져오지 못할 수 있습니다.
        print(f"[함선 별명] GitHub 대체 경로에서 {len(aliases)}개 함선 별명 읽기 완료")
        return aliases
    except Exception as error:
        print(f"[함선 별명] GitHub 대체 경로도 로드 실패: {error}")
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
SHIP_BY_GAME_ID = {int(ship.get("艦船ID", 0) or 0): ship for ship in SHIPS}


def build_drop_ship_name_index():
    """API의 宗谷(AGS) 같은 표기도 게임 함선 ID로 CSV 계보와 연결합니다."""
    remaining = set(range(len(SHIPS)))
    index = {}
    while remaining:
        component = set()
        pending = [next(iter(remaining))]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(SHIP_GRAPH.get(current, set()) - component)
        remaining.difference_update(component)
        names = {normalize_ship_name(SHIPS[i].get("艦名", "")) for i in component}
        for i in component:
            ship_id = int(SHIPS[i].get("艦船ID", 0) or 0)
            index.setdefault(ship_id, set()).update(names)
    return index


DROP_SHIP_NAMES = build_drop_ship_name_index()


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
        f"화력 {ship.get('火力最大', '-')}/뇌장 {ship.get('雷装最大', '-')}/"
        f"대공 {ship.get('対空最大', '-')}/장갑 {ship.get('装甲最大', '-')}"
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
        result.append(f"- {next_stage} 개장 레벨: {next_level}")
        materials = remodel_materials.material_text(ship, next_candidate)
        if materials:
            result.append(materials)
    return "\n".join(result)


def load_ship_aircraft_rules():
    """탑재량과 별개인 게임 마스터의 함선별 항공기 장착 규칙을 읽습니다."""
    try:
        with open(SHIP_AIRCRAFT_RULES_FILE, encoding="utf-8") as file:
            data = json.load(file)
        rules = data["ships"]
        categories = {int(category) for category in data["aircraft_categories"]}
        if data.get("schema_version") != 1 or not isinstance(rules, dict):
            raise ValueError("항공기 장착 규칙 파일의 형식이 올바르지 않습니다.")
        for ship_id, allowed in rules.items():
            if not ship_id.isdigit() or not isinstance(allowed, list):
                raise ValueError("함선별 장착 규칙의 형식이 올바르지 않습니다.")
            if any(type(category) is not int or category not in categories for category in allowed):
                raise ValueError("알 수 없는 항공기 장비 종류입니다.")
        return rules
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"[항공기 장착 규칙] 읽기 실패: {error}")
        return {}


SHIP_AIRCRAFT_RULES = load_ship_aircraft_rules()
NO_AIRCRAFT_MESSAGE = "수상기/함재기를 장착할 수 없습니다"


def ship_aircraft_status(ship):
    """True: 장착 가능, False: 불가, None: 미확인. 탑재량으로 추정하지 않습니다."""
    allowed = SHIP_AIRCRAFT_RULES.get(str(ship.get("艦船ID", "")))
    return bool(allowed) if allowed is not None else None


def ship_slot_text(ship):
    """실제 슬롯의 0을 보존하고, 장착 가능 여부는 별도 규칙으로 판단합니다."""
    result = [f"[{ship_stage(ship)}]"]
    status = ship_aircraft_status(ship)
    if status is False:
        return "\n".join(result + [NO_AIRCRAFT_MESSAGE])

    try:
        slot_count = int(ship.get("スロット数", "0") or 0)
    except (TypeError, ValueError):
        slot_count = 0
    slot_count = max(0, min(slot_count, 5))

    if slot_count == 0:
        result.append("탑재 슬롯 없음")
    else:
        capacities = []
        for index in range(1, slot_count + 1):
            raw_value = ship.get(f"搭載機数{index}")
            value = str(raw_value).strip() if raw_value is not None else "-"
            capacities.append(value or "-")
        result.append(" / ".join(capacities))
        if all(value == "0" for value in capacities):
            if status is True:
                result.append("항공기 장착 가능 · 탑재량 0")
            else:
                result.append("항공기 장착 가능 여부 미확인")
    return "\n".join(result)


def build_ship_slots_reply(keyword):
    if not keyword:
        return "사용법: !슬롯 함선명"
    results = search_ships(keyword)
    if not results:
        return f"'{keyword}' 칸무스를 찾지 못했습니다."
    if all(ship_aircraft_status(ship) is False for ship, _name in results):
        return NO_AIRCRAFT_MESSAGE
    return "\n\n".join(ship_slot_text(ship) for ship, _name in results)


def build_improvement_reply(keyword):
    data = improvement.catalog()
    query = keyword.strip()
    # Exact equipment names and equipment aliases always keep the existing
    # equipment lookup, even when a ship happens to have the same nickname.
    equipment_key = equipment_lookup.normalize(query)
    ship_matches = []
    selected_stage = None
    if query and equipment_key not in data.equipment.names and not query.startswith('#'):
        ship_matches = search_ships(query)
        if ship_matches:
            exact_forms = [ship_stage(ship) for ship, _ in ship_matches
                           if normalize_ship_name(query) in {
                               normalize_ship_name(ship['艦名']),
                               normalize_ship_name(SHIP_TRANSLATIONS.get(ship['艦名'], '')),
                           }]
            if exact_forms and exact_forms[0] != '미개장':
                selected_stage = exact_forms[0]
        else:
            stage_match = re.fullmatch(r'(.+?)(개(?:[123]|3호)?)', query)
            if stage_match:
                candidates = search_ships(stage_match[1])
                stage = '개1' if stage_match[2] == '개' else stage_match[2]
                if any(ship_stage(ship) == stage for ship, _ in candidates):
                    ship_matches = candidates
                    selected_stage = stage
    ship_names = {}
    ship_forms = {}
    # 최신 함선 중 ships.csv 갱신보다 먼저 개수 데이터에 추가된 함선입니다.
    # 개수 데이터의 2번함 ID도 기존 번역/별명 체계로 표시합니다.
    improvement_extra_names = {
        943: "쿠마노마루[미개장]",
        948: "쿠마노마루[개1]",
    }
    ship_names.update(improvement_extra_names)
    ship_forms.update({
        943: ("쿠마노마루", "미개장", 0),
        948: ("쿠마노마루", "개1", 1),
    })
    for ship in SHIPS:
        ship_id = int(ship["艦船ID"])
        japanese = ship["艦名"]
        name = development.translated_ship_name(japanese, SHIP_TRANSLATIONS)
        if name == japanese:
            # Include Korean base names registered only in the alias file.
            for canonical in sorted(SHIP_ALIASES, key=len, reverse=True):
                if not japanese.startswith(canonical):
                    continue
                korean = next((alias for alias in SHIP_ALIASES[canonical] if re.search(r"[가-힣]", alias)), None)
                if korean:
                    name = korean + development.remodel_suffix(japanese[len(canonical):])
                    break
        # The same Japanese name can refer to distinct convertible forms.
        if japanese in ("宗谷", "Glorious", "Glorious改"):
            name = f"{SHIP_TRANSLATIONS.get(japanese, name)} {ship_stage(ship)}"
        else:
            name = re.sub(r"(?<=[가-힣])(?=개(?:[123]|$))", " ", name)
            if name.endswith(" 개"):
                name += "1"
        ship_names[ship_id] = name
        base = SHIP_BY_GAME_ID.get(data.families.get(ship_id, ship_id), ship)
        japanese_base = base["艦名"]
        base_name = development.translated_ship_name(japanese_base, SHIP_TRANSLATIONS)
        if base_name == japanese_base:
            base_name = next((alias for alias in SHIP_ALIASES.get(japanese_base, [])
                              if re.search(r"[가-힣]", alias)), base_name)
        ship_forms[ship_id] = (base_name, ship_stage(ship), int(ship["改装段階"]))
    # The improvement dataset can contain newer helper IDs before ships.csv
    # has received their translated display records.
    ship_names.update(improvement_extra_names)
    ship_forms.update({
        943: ("쿠마노마루", "미개장", 0),
        948: ("쿠마노마루", "개1", 1),
    })
    if ship_matches:
        family_ids = {data.families.get(int(ship['艦船ID']), int(ship['艦船ID']))
                      for ship, _ in ship_matches}
        if len(family_ids) == 1:
            chosen = [int(ship['艦船ID']) for ship, _ in ship_matches
                      if selected_stage is None or ship_stage(ship) == selected_stage]
            if chosen:
                base_id = next(iter(family_ids))
                base_name = ship_forms.get(base_id, (ship_forms[chosen[0]][0],))[0]
                title = f'{base_name} [{selected_stage}]' if selected_stage else base_name
                return data.describe_ship(chosen, title, ship_forms)
    return data.reply(keyword, ship_names, ship_forms)


def build_initial_equipment_reply(keyword):
    keyword = keyword.strip()
    if not keyword:
        return "사용법: !초기장비 [칸무스]"
    results = search_ships(keyword)
    if not results:
        return f"'{keyword}' 칸무스를 찾지 못했습니다."
    data = initial_equipment.catalog()
    return "\n\n".join(data.form_text(ship, ship_stage(ship)) for ship, _name in results)


def build_fit_reply(arguments):
    keyword = arguments.strip()
    if not keyword:
        return "사용법: !피트 함선명"
    results = search_ships(keyword)
    if not results:
        return f"'{keyword}' 칸무스를 찾지 못했습니다."
    data = fit_bonus.catalog()
    forms = []
    for ship, _name in results:
        ship_id = int(ship["艦船ID"])
        if str(ship_id) not in data.ships:
            raise ValueError(f"함선 ID {ship_id}의 피트 판정 정보가 없습니다.")
        forms.append((ship_id, ship_stage(ship)))
    return fit_bonus.format_message(keyword, forms)


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
    "흰색팬티", "검정색팬티", "회색팬티", "연회색팬티", "빨강색팬티", "와인색팬티",
    "분홍색팬티", "연분홍색팬티", "보라색팬티", "연보라색팬티", "연파랑색팬티", "남색팬티",
    "하늘색팬티", "초록색팬티", "연두색팬티", "갈색팬티", "연갈색팬티", "베이지색팬티",
    "아이보리색팬티", "살구색팬티", "노랑색팬티",
    "검정 T팬티", "흰색 T팬티", "빨강 T팬티", "분홍 T팬티", "남색 T팬티", "하늘색 T팬티",
    "검정 레이스팬티", "흰색 레이스팬티", "분홍 레이스팬티",
    "검정 리본팬티", "흰색 리본팬티", "분홍 리본팬티", "빨강 리본팬티",
    "검정 줄무늬팬티", "흰색 줄무늬팬티", "빨강 줄무늬팬티", "파랑 줄무늬팬티",
    "분홍 줄무늬팬티", "검정 땡땡이팬티", "흰색 땡땡이팬티", "빨강 땡땡이팬티",
    "파랑 땡땡이팬티", "분홍 땡땡이팬티", "체크무늬팬티", "꽃무늬팬티", "하트무늬팬티",
    "별무늬팬티", "캐릭터팬티", "짱구팬티", "키티팬티", "곰돌이팬티",
    "토끼팬티", "노팬티",
]

PANTY_COMMAND = re.compile(r"^!(.+)팬티$")
WIFE_COMMAND = re.compile(r"^![^!\s]+아내$")


def random_wife_name():
    # The alias file has one entry per ship family, so remodels do not
    # give a ship additional chances of being selected.
    candidates = [
        SHIP_TRANSLATIONS.get(canonical) or next(
            (alias for alias in aliases if re.search(r"[가-힣]", alias)), canonical
        )
        for canonical, aliases in SHIP_ALIASES.items()
    ]
    return random.choice(candidates) if candidates else "칸무스 목록을 불러오지 못했습니다."


def kanlog_ship_name(ship_id, original):
    ship = SHIP_BY_GAME_ID.get(ship_id)
    japanese = ship['艦名'] if ship else original
    translated = SHIP_TRANSLATIONS.get(japanese, '')
    if re.search(r'[가-힣]', translated):
        return translated
    return next((alias for alias in SHIP_ALIASES.get(japanese, [])
                 if re.search(r'[가-힣]', alias)), translated or original)


def kanlog_ship_ids(keyword):
    """Resolve a ship name or alias to every remodel in its ship family."""
    return {
        int(ship.get("艦船ID", 0) or 0)
        for ship, _ in search_ships(keyword)
        if int(ship.get("艦船ID", 0) or 0) > 0
    }


def kanlog_limited_ship_info(ship_id, original):
    info = fit_bonus.catalog().ships.get(str(ship_id))
    if info is None:
        raise ValueError(f"한정 드랍 함선 정보 미등록: {ship_id}")
    family_id = info['base']
    base = SHIP_BY_GAME_ID.get(family_id)
    name = kanlog_ship_name(family_id, base['艦名'] if base else original)
    return family_id, name, info['type']

COMMANDS = {
    "!도움말": (
        "사용 가능한 명령어:\n"
        "!공지 !통합공략 !단발퀘 !반복퀘 !멘테 !월간원정\n"
        "!이벤트 !개구리야 !미르야\n"
        "!전과 [5/20/100/500]\n"
        "!드랍 [해역/함선명]\n"
        "!기간한정\n"
        "!칸무스 [함선명]\n"
        "!슬롯 [함선명]\n"
        "!초기장비 [함선명]\n"
        "!피트 [함선명]\n"
        "!장비 [장비명]\n"
        "!개발 [장비명]\n"
        "!레시피 [함선명] [연/탄/강/보]\n"
        "!개수 [장비명/함선명]\n"
        "![함선명]팬티\n"
        "![닉네임]아내"
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

    if message in ('!기간한정', '!한정드랍'):
        reply = kanlog_drops.format_limited_reply(
            KANLOG_DROPS.snapshot, kanlog_ship_name
        )
        response = requests.post(
            IRIS_REPLY_URL,
            json={'type': 'text', 'room': str(chat_id), 'data': reply},
            timeout=10,
        )
        print(f"[칸로그 한정 드랍 답변] 상태 코드={response.status_code}")
        return jsonify({'ok': True})

    if message == '!드랍' or message.startswith('!드랍 '):
        reply = kanlog_drops.format_reply(
            message, KANLOG_DROPS.snapshot, kanlog_ship_name, kanlog_ship_ids
        )
        response = requests.post(
            IRIS_REPLY_URL,
            json={'type': 'text', 'room': str(chat_id), 'data': reply},
            timeout=10,
        )
        print(f"[칸로그 드랍 답변] 상태 코드={response.status_code}")
        return jsonify({'ok': True})

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

    if message == "!초기장비" or message.startswith("!초기장비 "):
        try:
            reply = build_initial_equipment_reply(message[len("!초기장비"):])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[초기장비 조회 실패] {error}")
            reply = "초기 장비 데이터를 불러오지 못했습니다."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[초기장비 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!슬롯" or message.startswith("!슬롯 "):
        keyword = message[len("!슬롯"):].strip()
        reply = build_ship_slots_reply(keyword)

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
        print(f"[함선 슬롯 검색] 함선={keyword or '(미입력)'}, 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!피트" or message.startswith("!피트 "):
        try:
            reply = build_fit_reply(message[len("!피트"):])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[피트 조회 실패] {error}")
            reply = "피트 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[피트 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!개수" or message.startswith("!개수 "):
        try:
            reply = build_improvement_reply(message[len("!개수"):])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[개수 조회 실패] {error}")
            reply = "개수 데이터를 불러오지 못했습니다."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[개수 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!레시피" or message.startswith("!레시피 "):
        try:
            reply = development.build_recipe_reply(message[len("!레시피"):], SHIP_TRANSLATIONS, SHIP_ALIASES)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[레시피 조회 실패] {error}")
            reply = "레시피 데이터를 불러오지 못했습니다."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[레시피 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!개발" or message.startswith("!개발 "):
        try:
            reply = development.build_reply(message[len("!개발"):])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[개발 조회 실패] {error}")
            reply = "개발 데이터를 불러오지 못했습니다."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[개발 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if message == "!장비" or message.startswith("!장비 "):
        try:
            reply = equipment_lookup.build_reply(message[len("!장비"):])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"[장비 조회 실패] {error}")
            reply = "장비 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[장비 검색] 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    if WIFE_COMMAND.fullmatch(message):
        reply = "이나즈마" if message in {"!깡갤아내", "!왕갤아내", "!킹갤아내"} else random_wife_name()
        response = requests.post(
            IRIS_REPLY_URL,
            json={"type": "text", "room": str(chat_id), "data": reply},
            timeout=10,
        )
        print(f"[랜덤 칸무스] 결과={reply}, 상태 코드={response.status_code}")
        return jsonify({"ok": True})

    panty_match = PANTY_COMMAND.fullmatch(message)

    if panty_match:
        character = panty_match.group(1)
        reply = random.choice(PANTY_COLORS)

        print(f"[랜덤 팬티] 캐릭터={character}, 결과={reply}")

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

    if message in COMMANDS or message in ("!도움", "!명령어", "!명령"):
        reply = COMMANDS["!도움말"] if message in ("!도움", "!명령어", "!명령") else COMMANDS[message]

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
    KANLOG_DROPS.start()
    app.run(host="0.0.0.0", port=5000)
