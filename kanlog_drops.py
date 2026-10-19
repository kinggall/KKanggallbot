"""Kanlog HTML snapshots. Commands never perform network requests."""
import json
import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

URL = "https://kanlog.info/map/55/"
MAPS = tuple(f'{area}-{number}' for area, count in ((1, 6), (2, 5), (3, 5), (4, 5), (5, 6), (6, 5), (7, 5))
             for number in range(1, count + 1))
BOSS_STAGES = {'5-6': ('G', 'N', 'Z'), '7-2': ('G', 'M'),
               '7-3': ('E', 'P'), '7-5': ('K', 'Q', 'T')}
JST = timezone(timedelta(hours=9))
LOG = logging.getLogger(__name__)
USAGE = "사용법: !드랍 [해역] / !드랍 [함선명]\n예: !드랍 55p / !드랍 후부키"
LIMITED_GROUPS = ('전함', '항모', '중순', '경순', '구축', '해방', '잠수', '보조')
RARE_URL = 'https://kanlog.info/rare/'
RARE_GROUPS = {
    'senkan': '전함', 'kubo': '항모', 'jyujyun': '중순', 'keijyun': '경순',
    'kutikukan': '구축', 'kaiboukan': '해방', 'sensuikan': '잠수', 'hojo': '보조',
}
RARE_TASK = 'rare-index'
# The user verified these two 2-4-P records ended, although their old
# observations remain in Kanlog's 2026/06/26–present statistics.
ENDED_LOCATIONS = {('2-4', 'P', 952), ('2-4', 'P', 941)}


def map_url(map_name):
    return f"https://kanlog.info/map/{map_name.replace('-', '')}/"


class MapParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.rows = []
        self.scripts = {}
        self.script_id = None
        self.script_parts = []
        self.button = None
        self.button_text = []
        self.text = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'script':
            self.script_id = a.get('id')
            self.script_parts = []
        if tag == 'button' and a.get('data-cell-no') and a.get('data-cell-label'):
            self.button = a
            self.button_text = []
        if tag == 'tr' and 'js-drop-rate-row' in a.get('class', '').split():
            self.rows.append(a)

    def handle_data(self, data):
        if self.script_id:
            self.script_parts.append(data)
        if self.button is not None:
            self.button_text.append(data)
        if not self.skip and data.strip():
            self.text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == 'script' and self.script_id:
            if self.script_id in ('drop-rate-row-variant-data', 'drop-rate-rank-variant-total-data'):
                self.scripts[self.script_id] = json.loads(''.join(self.script_parts))
            self.script_id = None
        if tag in ('script', 'style'):
            self.skip -= 1
        if tag == 'button' and self.button is not None:
            self.cells[self.button['data-cell-no']] = {
                'label': self.button['data-cell-label'],
                'boss': 'Boss' in ''.join(self.button_text),
            }
            self.button = None


def parse_page(html, map_name='5-5'):
    if map_name not in MAPS:
        raise ValueError('Unknown normal map')
    parser = MapParser()
    parser.feed(html)
    variants = parser.scripts['drop-rate-row-variant-data']
    totals = parser.scripts['drop-rate-rank-variant-total-data']
    text = '\n'.join(parser.text)
    period = re.search(r'集計:\s*(\d{4}/\d{2}/\d{2})\s*～\s*更新:\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', text)
    if not period or not parser.cells or (map_name != '1-6' and not any(c['boss'] for c in parser.cells.values())):
        raise ValueError('Kanlog map metadata missing')
    # Numbering is explicit game-map knowledge, never HTML display order.
    if map_name in BOSS_STAGES:
        actual = {c['label'] for c in parser.cells.values() if c['boss']}
        if actual != set(BOSS_STAGES[map_name]):
            raise ValueError(f'Kanlog boss mapping changed: {map_name}: {actual}')
    rows = []
    for raw in parser.rows:
        meta = json.loads(raw['data-m'])
        key = raw['data-row-key']
        cell = key.split('-')[0]
        if raw['data-map-lv'] != '0':
            continue
        if cell not in parser.cells or len(meta) < 16:
            raise ValueError('Kanlog row metadata mismatch')
        ranks = {}
        for rank in ('s', 'a'):
            total = totals.get('0:' + rank, {}).get(cell, 0)
            value = variants.get(key, {}).get(rank)
            if value is not None:
                if total <= 0 or abs(value['r'] - value['c'] * 100 / total) > 0.00011:
                    raise ValueError('Kanlog drop denominator mismatch')
                ranks[rank] = {'rate': value['r'], 'count': value['c']}
        rows.append({'cell': cell, 'ship_id': int(raw['data-ship-id']),
                     'name': raw['data-ship-name'], 'rarity': meta[1],
                     'limited': bool(meta[10]), 'ranks': ranks})
    if not rows:
        raise ValueError('Kanlog drop rows missing')
    # Include common ships and No Drop in this validation, even though the
    # reply filters them out. Missing rows must not silently bias results.
    for cell in parser.cells:
        for rank in ('s', 'a'):
            count = sum(row['ranks'].get(rank, {}).get('count', 0)
                        for row in rows if row['cell'] == cell)
            if count != totals.get('0:' + rank, {}).get(cell, 0):
                raise ValueError(f'Kanlog incomplete sample totals: {map_name}/{cell}/{rank}')
    return {'schema': 1, 'map': map_name, 'source': map_url(map_name),
            'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
            'period_start': period[1], 'source_updated': period[2],
            'cells': parser.cells, 'totals': totals, 'rows': rows}


def parse_map_query(query):
    # Only two map digits and an optional ASCII node label qualify as a
    # map. Names such as 이26 / U-511 must remain ship queries in future.
    match = re.fullmatch(r'([1-7])-?([1-6])(?:-?([a-z][0-9]?)|-([1-3]))?(?:\s+([sa]))?', query.strip(), re.I)
    if not match:
        return None
    return (f'{match[1]}-{match[2]}', match[3].upper() if match[3] else match[4],
            match[5].lower() if match[5] else None)


class RareIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.panel = None
        self.panel_depth = 0
        self.card = None
        self.card_depth = 0
        self.name_depth = 0
        self.badge_depth = 0
        self.groups = {group: [] for group in LIMITED_GROUPS}
        self.card_counts = {group: 0 for group in LIMITED_GROUPS}
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        self.depth += 1
        data = dict(attrs)
        classes = data.get('class', '').split()
        if tag == 'div' and 'rare-drop-index__type-panel' in classes:
            self.panel = RARE_GROUPS.get(data.get('data-rare-ship-type'))
            if self.panel is not None:
                self.seen.add(self.panel)
                self.panel_depth = self.depth
        if self.panel is not None and tag == 'a' and 'rare-drop-index__link' in classes:
            self.card = {'name_parts': [], 'limited': False}
            self.card_depth = self.depth
        if self.card is not None and tag == 'span' and 'rare-drop-index__name' in classes:
            self.name_depth = self.depth
        if self.card is not None and tag == 'span' and 'rare-drop-index__limited-badge' in classes:
            self.card['limited'] = True
            self.badge_depth = self.depth

    def handle_data(self, data):
        if self.card is not None and self.name_depth and not self.badge_depth:
            self.card['name_parts'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.card is not None and self.depth == self.card_depth:
            name = ''.join(self.card['name_parts']).strip()
            if not name:
                raise ValueError('Kanlog rare index ship name missing')
            self.card_counts[self.panel] += 1
            if self.card['limited']:
                self.groups[self.panel].append(name)
            self.card = None
        if tag == 'span' and self.depth == self.badge_depth:
            self.badge_depth = 0
        if tag == 'span' and self.depth == self.name_depth:
            self.name_depth = 0
        if tag == 'div' and self.panel is not None and self.depth == self.panel_depth:
            self.panel = None
        self.depth -= 1


def parse_rare_page(html):
    parser = RareIndexParser()
    parser.feed(html)
    updated = re.search(r'<time datetime="([0-9TZ:.-]+)"', html)
    if parser.seen != set(LIMITED_GROUPS) or any(not count for count in parser.card_counts.values()) or not updated:
        raise ValueError('Kanlog rare index structure changed')
    source_updated = datetime.fromisoformat(updated[1].replace('Z', '+00:00')).astimezone(JST)
    groups = parser.groups
    if any(len(values) != len(set(values)) for values in groups.values()):
        raise ValueError('Kanlog rare index duplicated ship cards')
    return {'schema': 1, 'source': RARE_URL,
            'source_updated': source_updated.strftime('%Y/%m/%d %H:%M:%S'),
            'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
            'groups': groups}


def format_limited_reply(snapshot, name_for):
    """List only the cards with a 期間限定 badge on Kanlog's rare page."""
    rare = snapshot.get('rare')
    if rare is None:
        return '기간한정 목록을 준비 중입니다.'
    lines = []
    for group in LIMITED_GROUPS:
        names = rare['groups'][group]
        if names:
            translated = [name_for(0, name) for name in names]
            lines.append(f'[{group}]\n' + ' / '.join(translated))
    return '\n\n'.join(lines) if lines else '현재 확인된 기간한정 드랍이 없습니다.'


def is_ended_location(map_name, cells, row):
    return (map_name, cells.get(row['cell'], {}).get('label'), row['ship_id']) in ENDED_LOCATIONS


def _format_ship_drop_reply(keyword, snapshot, name_for, ship_ids_for):
    """Return the best cached map/cell records for a ship or alias."""
    ship_ids = {int(value) for value in ship_ids_for(keyword)}
    if not ship_ids:
        return USAGE
    maps = snapshot.get('maps', {}) if 'maps' in snapshot else {snapshot.get('map'): snapshot}
    found = []
    for map_name, data in maps.items():
        if not data:
            continue
        for row in data.get('rows', []):
            if row.get('ship_id') not in ship_ids:
                continue
            if is_ended_location(map_name, data.get('cells', {}), row):
                continue
            values = row.get('ranks', {})
            if not any(item.get('count', 0) > 0 for item in values.values()):
                continue
            cell = data.get('cells', {}).get(row.get('cell'), {})
            found.append({
                'map': map_name,
                'label': cell.get('label', row.get('cell', '?')),
                'boss': bool(cell.get('boss')),
                'limited': bool(row.get('limited')),
                'ranks': values,
            })
    found.sort(key=lambda item: (
        -max((value.get('rate', 0) for value in item['ranks'].values()), default=0),
        item['map'], item['label']))
    lines = [f"{keyword} Drop Table"]
    for item in found[:25]:
        location = f"{item['map']} Boss" if item['boss'] else f"{item['map']} {item['label']}"
        parts = []
        for rank in ('s', 'a'):
            value = item['ranks'].get(rank)
            if value and value.get('count', 0) > 0:
                rate = '<0.01%' if value['rate'] < 0.01 else f"{value['rate']:.2f}%"
                parts.append(f"{rank.upper()} {rate}")
        suffix = ' (한정)' if item['limited'] else ''
        lines.append(f"· {location} - {' / '.join(parts)}{suffix}")
    if len(lines) == 1:
        lines.append('· 확인된 드랍 기록이 없습니다.')
    return '\n'.join(lines)


def format_reply(message, snapshot, name_for, ship_ids_for=None):
    match = re.fullmatch(r'!드랍\s+(.+)', message)
    if not match:
        return USAGE
    query = match[1].strip()
    parsed = parse_map_query(query)
    if parsed is None:
        if ship_ids_for is None:
            return USAGE
        return _format_ship_drop_reply(query, snapshot, name_for, ship_ids_for)
    if parsed is None or parsed[0] not in MAPS:
        return USAGE
    map_name, label, rank = parsed
    if 'maps' in snapshot:
        snapshot = snapshot['maps'].get(map_name)
    elif snapshot['map'] != map_name:
        snapshot = None
    if snapshot is None:
        return f'{map_name} 드랍 자료를 준비 중입니다.'
    cells = snapshot['cells']
    display_label = label
    if label and label.isdigit():
        stages = BOSS_STAGES.get(map_name, ())
        if not 1 <= int(label) <= len(stages):
            return f'{map_name}에 해당 차수의 보스방이 없습니다.'
        label = stages[int(label) - 1]
    elif label is None and map_name in BOSS_STAGES:
        label = BOSS_STAGES[map_name][-1]
    chosen = next((key for key, cell in cells.items()
                   if (cell['label'] == label if label else cell['boss'])), None)
    if chosen is None:
        return (f"{map_name}에 {label}마스의 드랍 자료가 없습니다." if label
                else '보스방이 존재하지 않습니다.')
    title = f"{map_name}-{display_label} Drop" if display_label else f'{map_name} Boss Drop'
    if rank:
        title += f" ({rank.upper()}승)"
    else:
        title += ' (S/A)'
    lines = [title]
    rows = [row for row in snapshot['rows'] if row['cell'] == chosen
            and (row['rarity'] in ('rare', 'unique') or row['limited'])
            and not is_ended_location(map_name, cells, row)]
    selected = (rank,) if rank else ('s', 'a')
    rows.sort(key=lambda row: tuple(-row['ranks'].get(r, {}).get('rate', 0) for r in selected)
              + (row['ship_id'],))
    for row in rows:
        parts = []
        for r in selected:
            value = row['ranks'].get(r)
            if value and value['count'] > 0:
                percent = '<0.01%' if value['rate'] < 0.01 else f"{value['rate']:.2f}%"
                parts.append(f"{r.upper()} {percent}")
        if parts:
            suffix = ' (한정)' if row['limited'] else ''
            lines.append(f"· {name_for(row['ship_id'], row['name'])} - {' / '.join(parts)}{suffix}")
    if len(lines) == 1:
        lines.append('· 해당 조건의 레어·한정 드랍 기록이 없습니다.')
    return '\n'.join(lines)


def next_refresh(now):
    """01:15, 05:15, ... 21:15 Korean/Japanese local time."""
    local = datetime.fromtimestamp(now, JST)
    for offset in (0, 1):
        day = local + timedelta(days=offset)
        for hour in (1, 5, 9, 13, 17, 21):
            candidate = day.replace(hour=hour, minute=15, second=0, microsecond=0)
            if candidate.timestamp() > now:
                return candidate.timestamp()


class DropStore:
    def __init__(self, cache_dir):
        self.path = Path(cache_dir) / 'kanlog_maps.json'
        self.lock = threading.Lock()
        self.started = False
        seed = Path(__file__).parent / 'data' / 'kanlog_maps_seed.json'
        self.snapshot = json.loads(seed.read_text(encoding='utf-8'))
        rare_seed = Path(__file__).parent / 'data' / 'kanlog_rare_seed.json'
        self.snapshot['rare'] = json.loads(rare_seed.read_text(encoding='utf-8'))
        self.remaining = []
        self.due = next_refresh(time.time())
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if saved['snapshot']['schema'] != 2 or set(saved['snapshot']['maps']) != set(MAPS):
                raise ValueError('Unexpected Kanlog cache schema')
            # Never replace newer packaged data with an older user cache.
            for name, old in saved['snapshot']['maps'].items():
                if old['source_updated'] > self.snapshot['maps'][name]['source_updated']:
                    self.snapshot['maps'][name] = old
            saved_rare = saved['snapshot'].get('rare')
            if saved_rare and saved_rare['source_updated'] > self.snapshot['rare']['source_updated']:
                self.snapshot['rare'] = saved_rare
            self.due = saved['next_attempt']
            self.remaining = saved.get('remaining', [])
            if not isinstance(self.remaining, list) or any(name not in (*MAPS, RARE_TASK) for name in self.remaining):
                raise ValueError('Unexpected Kanlog pending maps')
        except (OSError, ValueError, KeyError, TypeError):
            self.remaining = []
            self.due = next_refresh(time.time())
        # Carry over the earlier 5-5-only cache without deleting it.
        try:
            old = json.loads((Path(cache_dir) / 'kanlog_55.json').read_text(encoding='utf-8'))['snapshot']
            if old['map'] == '5-5' and old['source_updated'] > self.snapshot['maps']['5-5']['source_updated']:
                self.snapshot['maps']['5-5'] = old
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not self.path.exists():
            self.save(self.snapshot, self.due)

    def save(self, snapshot, due):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'snapshot': snapshot, 'next_attempt': due,
                                        'remaining': self.remaining}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def refresh_if_due(self, now=None):
        now = time.time() if now is None else now
        if not self.lock.acquire(blocking=False):
            return
        try:
            if now < self.due:
                return
            if not self.remaining:
                self.remaining = list(MAPS) + [RARE_TASK]
            pending = list(self.remaining)
            map_name = self.remaining[0]
            # Persist the retry boundary before fetching so restarts after a
            # failed request do not cause repeated access to the site.
            self.due = now + 3600
            self.save(self.snapshot, self.due)
            try:
                response = requests.get(RARE_URL if map_name == RARE_TASK else map_url(map_name), timeout=(10, 30), headers={
                    'User-Agent': 'KKanggallbot/1.0 (+https://github.com/kinggall/KKanggallbot)',
                    'Accept': 'text/html',
                })
                response.raise_for_status()
                fresh = parse_rare_page(response.text) if map_name == RARE_TASK else parse_page(response.text, map_name)
                previous = self.snapshot['rare'] if map_name == RARE_TASK else self.snapshot['maps'][map_name]
                if fresh['source_updated'] < previous['source_updated']:
                    raise ValueError('Older source data, preserving newer cached snapshot')
                updated = {'schema': 2, 'maps': dict(self.snapshot['maps']), 'rare': self.snapshot['rare']}
                if map_name == RARE_TASK:
                    updated['rare'] = fresh
                else:
                    updated['maps'][map_name] = fresh
                self.remaining = self.remaining[1:]
                # One request per step, including across restarts. No burst
                # of parallel calls and no full restart of a partial sweep.
                self.due = time.time() + 10 if self.remaining else next_refresh(time.time())
                self.save(updated, self.due)
                self.snapshot = updated
                LOG.warning('[칸로그] %s 저장 완료, 남은 해역 %d, 자료 갱신: %s',
                            map_name, len(self.remaining), fresh['source_updated'])
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, OSError):
                self.remaining = pending
                self.due = time.time() + 3600
                self.save(self.snapshot, self.due)
                LOG.exception('[칸로그] 수집 실패, 저장 자료 유지. 1시간 후 재시도')
        finally:
            self.lock.release()

    def start(self):
        if self.started:
            return
        self.started = True
        def run():
            while True:
                try:
                    self.refresh_if_due()
                except OSError:
                    LOG.exception('[칸로그] 캐시 저장 실패')
                time.sleep(1)
        threading.Thread(target=run, name='kanlog-refresh', daemon=True).start()
