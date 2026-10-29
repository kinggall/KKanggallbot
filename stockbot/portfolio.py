"""Read-only Domino snapshot. Private values stay in memory, never in Git/cache."""
import json
import os
from pathlib import Path
import threading
import time
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, localcontext

from .stock_quotes import normalize, number, KST
from .security_names import USSecurityNames, KNOWN_US_SYMBOLS
from .aliases import lookup, name_targets, US_NAMES
from .unlisted import UNLISTED_NAMES
from .etf_brands import match_etfs
from .us_catalog import find_names, get_record

FILE_ID = '1xclx9sD8c1Bh4mnrleGaJDToAsZG5UU6'
TRADE_LEDGER_YEAR = 2026


def trade_date_text(value):
    """Yearless app trade dates belong to the explicitly selected 2026 ledger."""
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?', text)
    if match:
        try:
            return datetime(TRADE_LEDGER_YEAR, int(match[1]), int(match[2])).date().isoformat()
        except ValueError:
            return '미확인'
    return date_text(value)


def date_text(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.astimezone(KST).date().isoformat() if stamp.tzinfo else stamp.date().isoformat()
    except (ValueError, TypeError):
        return '미확인'


def percent_text(value):
    parsed = number(value)
    if parsed is None:
        return '미확인'
    with localcontext() as context:
        context.rounding = ROUND_HALF_UP
        return f'{parsed:.2f}%'


def arrow_percent(value):
    parsed = number(value)
    if parsed is None:
        return '미확인'
    return ('▲' if parsed > 0 else '▼' if parsed < 0 else '') + percent_text(abs(parsed))


def load_snapshot():
    from scripts.sync_drive_data import Drive, API
    token = os.environ.get('KAKAO_STOCK_DRIVE_TOKEN_FILE')
    default = Path(__file__).resolve().parents[1] / 'cloud' / 'token.json'
    if not token and default.is_file():
        token = str(default)
    drive = Drive(os.environ.get('GOOGLE_DRIVE_FOLDER_ID', ''), token)
    response = drive.call('GET', API + '/' + os.environ.get('KAKAO_STOCK_PORTFOLIO_FILE_ID', FILE_ID),
                          params={'alt': 'media'})
    # Drive serves this JSON as text/plain: requests.json() may guess Latin-1.
    return json.loads(response.content.decode('utf-8-sig'))


def display(value, suffix=''):
    parsed = number(value)
    if parsed is None:
        return '미확인'
    text = format(parsed, ',f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text + suffix


class PortfolioService:
    def __init__(self, loader=load_snapshot, monotonic=time.monotonic, name_loader=None, quote_loader=None, symbol_names=None, ticker_lookup=None):
        self.loader, self.monotonic = loader, monotonic
        self.lock = threading.Lock()
        self.cached = None
        self.loaded_at = 0
        self.name_loader = name_loader if name_loader is not None else USSecurityNames()
        self.quote_loader = quote_loader
        self.symbol_names = symbol_names
        self.ticker_lookup = ticker_lookup

    def position_text(self, rows, data):
        blocks = []
        for row in rows:
            unit = '원' if row.get('currency') == 'KRW' else ' USD' if row.get('currency') == 'USD' else ''
            live = {}
            if self.quote_loader and row.get('ticker'):
                try:
                    live = self.quote_loader(row['ticker'], row.get('currency'))
                except Exception:
                    pass
            price = live.get('price', row.get('current_price') if row.get('quote_available') is not False else None)
            change, percent = number(live.get('change')), number(live.get('percent'))
            daily = '미확인'
            if change is not None and percent is not None:
                arrow = '▲' if change > 0 else '▼' if change < 0 else ''
                sign = '+' if change > 0 else '-' if change < 0 else ''
                daily = sign + display(abs(change), unit) + ' (' + arrow + percent_text(abs(percent)) + ')'
            stamp = live.get('fetched_at') or row.get('quote_at') or data.get('quotes_read_at')
            blocks.append('\n'.join([
                '[' + row['name'] + ']',
                '✔️ 평균 매입가: ' + display(row.get('average'), unit),
                '✔️ 수익률: ' + percent_text(row.get('return_pct')),
                '✔️ 현재가: ' + display(price, unit),
                '✔️ 전일대비: ' + daily,
                '', '갱신 일자: ' + date_text(data['generated_at']),
                '시세 기준: ' + date_text(stamp),
            ]))
        return '\n\n'.join(blocks) if blocks else '등록된 자료가 없습니다.'

    def holdings_text(self, rows, generated_at, title='보유종목'):
        lines, seen = ['[' + title + ']'], set()
        for row in rows:
            symbol = str(row.get('ticker') or '').split(':')[-1].strip()
            identity = (row.get('currency'), symbol or normalize(row['name']))
            if identity in seen:
                continue
            seen.add(identity)
            if normalize(row['name']) in {normalize(name) for name in UNLISTED_NAMES}:
                lines.append(f'· {row["name"]}(비상장)')
            elif row.get('listing_market') == 'US' or row.get('currency') == 'USD':
                symbol = symbol or row['name']
                name = row.get('security_name') or row['name']
                if normalize(name) == normalize(symbol):
                    name = self.name_loader(symbol)
                lines.append(f'· {symbol}({name})')
            else:
                lines.append(f'· {row["name"]}({symbol or "코드 미확인"})')
        if not rows:
            lines.append('등록된 자료가 없습니다.')
        lines.extend(['', '갱신 일자: ' + date_text(generated_at)])
        return '\n'.join(lines)

    def realized_list(self, rows, data):
        enriched = []
        for row in rows:
            item = dict(row)
            if not item.get('ticker') or item['ticker'] in ('미확인', '코드 미확인'):
                holdings = [r for r in data['holdings']
                              if normalize(r['name']) == normalize(item['name'])
                              and r.get('ticker')]
                candidates = {str(r['ticker']) for r in holdings}
                if len(candidates) == 1:
                    item['ticker'] = next(iter(candidates))
                    if any(r.get('currency') == 'USD' for r in holdings):
                        item['listing_market'] = 'US'
                elif self.ticker_lookup:
                    try:
                        item['ticker'] = self.ticker_lookup(item['name'], item.get('currency'))
                    except Exception:
                        item['ticker'] = ''
            ticker = str(item.get('ticker') or '')
            symbol = (ticker.split(':')[-1] or item['name']).upper()
            us_prefix = ticker.split(':')[0] in ('NASDAQ', 'NYSE', 'NYSEARCA', 'NYSEAMERICAN', 'AMEX', 'NAS', 'NYS', 'AMS')
            # Realized profit can be converted to KRW even for US shares. Only
            # explicit venue, a verified public name, or a confirmed US symbol
            # identifies the listing market; do not overwrite the profit unit.
            if re.fullmatch(r'[A-Z]{1,6}(?:[.\-/][A-Z])?', symbol):
                try:
                    full_name = self.name_loader(symbol)
                except Exception:
                    full_name = '종목명 미확인'
                if (us_prefix or item.get('listing_market') == 'US' or item.get('currency') == 'USD'
                        or full_name != '종목명 미확인' or symbol in KNOWN_US_SYMBOLS or symbol in US_NAMES):
                    item['ticker'] = symbol
                    item['listing_market'] = 'US'
                    item['security_name'] = full_name
            enriched.append(item)
        return self.holdings_text(enriched, data['generated_at'], title='실현 수익률')

    def snapshot(self):
        with self.lock:
            if self.cached is not None and self.monotonic() - self.loaded_at < 30:
                return self.cached
            data = self.loader()
            if (not isinstance(data, dict) or data.get('schema_version') != 1
                    or not isinstance(data.get('generated_at'), str)
                    or not data['generated_at']
                    or any(not isinstance(data.get(k), list) for k in ('holdings', 'realized'))
                    or any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
                           for k in ('holdings', 'realized') for row in data[k])):
                raise ValueError('Unsupported Domino schema')
            self.cached, self.loaded_at = data, self.monotonic()
            return data

    def reply(self, command, keyword=''):
        if command not in ('보유', '실현'):
            return '지원하지 않는 자산 명령어입니다.'
        try:
            data = self.snapshot()
            rows = data['realized' if command == '실현' else 'holdings']
            key = normalize(keyword)
            if key:
                exact = [r for r in rows if key in (normalize(r['name']), normalize(r.get('ticker', '')).split(':')[-1])]
                if not exact:
                    matched = match_etfs(keyword, {index:r['name'] for index,r in enumerate(rows)})
                    exact = [r for index,r in enumerate(rows) if index in matched]
                if not exact:
                    alias = lookup(keyword)
                    targets = {normalize(n) for n in name_targets(keyword)}
                    if alias:
                        targets.update((normalize(alias[1]), normalize(alias[2])))
                    for symbol in find_names(keyword, exact_only=True):
                        record = get_record(symbol)
                        targets.update(normalize(n) for n in (symbol, record[1], *record[2]))
                    targets.update(normalize(r['name']) for r in data['holdings']
                                   if normalize(r.get('ticker', '')).split(':')[-1] == key)
                    if self.symbol_names:
                        try:
                            targets.update(normalize(n) for n in self.symbol_names(keyword))
                        except Exception:
                            pass
                    exact = [r for r in rows if normalize(r['name']) in targets or normalize(r.get('ticker', '')).split(':')[-1] in targets]
                matches = exact or [r for r in rows if key in normalize(r['name'])]
                names = sorted({r['name'] for r in matches})
                if not matches:
                    return '해당 종목의 자산 자료가 없습니다.'
                if len(names) > 1:
                    return '정확한 종목명을 입력해 주세요.\n' + '\n'.join('· ' + n for n in names)
                rows = matches
            if command == '보유':
                if key:
                    return self.position_text(rows, data)
                return self.holdings_text(rows, data['generated_at'])
            if not key:
                return self.realized_list(rows, data)
            lines = ['[실현 수익률]']
            if not rows:
                lines.append('등록된 자료가 없습니다.')
            for index, row in enumerate(rows):
                label = row['name']
                value = arrow_percent(row.get('return_pct'))
                if index:
                    lines.append('')
                lines.append('· ' + label + ': ' + value)
                lines.extend(['', '최종 거래일 : ' + trade_date_text(row.get('last_trade_date'))])
            if not rows:
                lines.append('')
            lines.append('갱신 일자: ' + date_text(data['generated_at']))
            return '\n'.join(lines)
        except Exception:
            # Never echo credentials, account identifiers, payload or provider errors.
            return 'Domino 자산 자료를 읽지 못했습니다. Drive 연결과 자료 갱신을 확인해 주세요.'
