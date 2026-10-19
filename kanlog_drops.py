"""Kanlog HTML snapshots. Commands never perform network requests."""
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

URL = "https://kanlog.info/map/55/"
JST = timezone(timedelta(hours=9))
LOG = logging.getLogger(__name__)
USAGE = "사용법: !드랍 5-5 / !드랍 5-5 S / !드랍 5-5 A / !드랍 5-5-P / !드랍 5-5-P S"


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


def parse_page(html):
    parser = MapParser()
    parser.feed(html)
    variants = parser.scripts['drop-rate-row-variant-data']
    totals = parser.scripts['drop-rate-rank-variant-total-data']
    text = '\n'.join(parser.text)
    period = re.search(r'集計:\s*(\d{4}/\d{2}/\d{2})\s*～\s*更新:\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', text)
    if not period or not parser.cells or not any(c['boss'] for c in parser.cells.values()):
        raise ValueError('Kanlog map metadata missing')
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
            total = totals['0:' + rank][cell]
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
    return {'schema': 1, 'map': '5-5', 'source': URL,
            'period_start': period[1], 'source_updated': period[2],
            'cells': parser.cells, 'totals': totals, 'rows': rows}


def format_reply(message, snapshot, name_for):
    match = re.fullmatch(r'!드랍\s+5-5(?:-([a-zA-Z]))?(?:\s+([sSaA]))?', message)
    if not match:
        return USAGE
    label = match[1].upper() if match[1] else None
    rank = match[2].lower() if match[2] else None
    cells = snapshot['cells']
    chosen = next((key for key, cell in cells.items()
                   if (cell['label'] == label if label else cell['boss'])), None)
    if chosen is None:
        return f"5-5에 {label}마스의 드랍 자료가 없습니다."
    title = f"5-5-{label} Drop" if label else '5-5 Boss Drop'
    if rank:
        title += f" ({rank.upper()}승)"
    lines = [title]
    rows = [row for row in snapshot['rows'] if row['cell'] == chosen
            and (row['rarity'] in ('rare', 'unique') or row['limited'])]
    selected = (rank,) if rank else ('s', 'a')
    rows.sort(key=lambda row: tuple(-row['ranks'].get(r, {}).get('rate', 0) for r in selected)
              + (row['ship_id'],))
    for row in rows:
        parts = []
        for r in selected:
            value = row['ranks'].get(r)
            if value and value['count'] > 0:
                percent = '<0.01%' if 0 < value['rate'] < 0.01 else f"{value['rate']:.2f}%"
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
        self.path = Path(cache_dir) / 'kanlog_55.json'
        self.lock = threading.Lock()
        self.started = False
        seed = Path(__file__).parent / 'data' / 'kanlog_55_seed.json'
        self.snapshot = json.loads(seed.read_text(encoding='utf-8'))
        self.due = 0
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if saved['snapshot']['schema'] != 1 or saved['snapshot']['map'] != '5-5':
                raise ValueError('Unexpected Kanlog cache schema')
            self.snapshot = saved['snapshot']
            self.due = saved['next_attempt']
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def save(self, snapshot, due):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'snapshot': snapshot, 'next_attempt': due}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def refresh_if_due(self, now=None):
        now = time.time() if now is None else now
        if not self.lock.acquire(blocking=False):
            return
        try:
            if now < self.due:
                return
            # Persist the retry boundary before fetching so restarts after a
            # failed request do not cause repeated access to the site.
            self.due = now + 3600
            self.save(self.snapshot, self.due)
            try:
                response = requests.get(URL, timeout=(10, 30), headers={
                    'User-Agent': 'KKanggallbot/1.0 (+https://github.com/kinggall/KKanggallbot)',
                    'Accept': 'text/html',
                })
                response.raise_for_status()
                fresh = parse_page(response.text)
                self.due = next_refresh(time.time())
                self.save(fresh, self.due)
                self.snapshot = fresh
                LOG.warning('[칸로그] 5-5 저장 완료, 자료 갱신: %s', fresh['source_updated'])
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, OSError):
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
                time.sleep(60)
        threading.Thread(target=run, name='kanlog-refresh', daemon=True).start()
