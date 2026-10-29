"""Public domestic/US stock quotes, independent of the Domino web server.

The existing PC adapter defaults to ~/projects/domino-code; credentials stay in
C:/domino. KAKAO_STOCK_CODE_DIR and KAKAO_STOCK_DATA_HOME override those paths.
Only the quote client and public listing helper are imported. No portfolio DB
is opened. Runtime caches use the user's cache folder, outside the Git checkout.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import importlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
import unicodedata

import requests
from .aliases import lookup as stock_alias, us_symbol, name_targets, preferred_bases

KST = timezone(timedelta(hours=9))
LOG = logging.getLogger(__name__)
USAGE = '종목명·티커로 입력해 주세요.\n예: !주가 삼성전자 / !주가 애플 / !주가 DRAM'


def domestic_session(when):
    local = when.astimezone(KST)
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5:
        return '장외'
    if 480 <= minute < 530:
        return 'NXT 프리'
    if 540 <= minute < 930:
        return '정규장'
    if 960 <= minute < 1200:
        return 'NXT 애프터'
    return '장외'


class QuoteError(ValueError):
    pass


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text))).casefold()


def number(value):
    try:
        result = Decimal(str(value).replace(',', ''))
        return result if result.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


def nonnegative(value):
    parsed = number(value)
    return parsed if parsed is not None and parsed >= 0 else None


@dataclass(frozen=True)
class StockQuote:
    name: str
    code: str
    price: Decimal
    change: object
    percent: object
    volume: object
    turnover: object
    fetched_at: datetime
    market_status: str = ''


def parse_quote(output, code, name, fetched_at, market_status=''):
    if not isinstance(output, dict) or output.get('stck_shrn_iscd') != code:
        raise QuoteError('종목 검증 실패')
    price = number(output.get('stck_prpr'))
    if price is None or price <= 0:
        raise QuoteError('현재가 미수신')
    previous = number(output.get('stck_prdy_clpr'))
    if previous is None or previous <= 0:
        delta = number(output.get('prdy_vrss'))
        sign = str(output.get('prdy_vrss_sign', ''))
        if delta is not None and sign in ('1', '2', '4', '5', '3'):
            signed = abs(delta) if sign in ('1', '2') else -abs(delta) if sign in ('4', '5') else Decimal(0) if delta == 0 else None
            previous = price - signed if signed is not None else None
    change = price - previous if previous is not None and previous > 0 else None
    percent = change / previous * 100 if change is not None else None
    return StockQuote(name, code, price, change, percent,
                      nonnegative(output.get('acml_vol')), nonnegative(output.get('acml_tr_pbmn')),
                      fetched_at, market_status)


def integer(value):
    return f'{int(value.to_integral_value(rounding=ROUND_DOWN)):,}'


def turnover_text(value):
    if value is None:
        return '—'
    if value >= Decimal('100000000'):
        return f'{value / Decimal("100000000"):,.2f}'.rstrip('0').rstrip('.') + '억원'
    return integer(value) + '원'


def format_quote(quote):
    direction = quote.change if quote.change is not None else Decimal(0)
    color = '🔴' if direction > 0 else '🔵' if direction < 0 else '⚪'
    arrow = '▲' if direction > 0 else '▼' if direction < 0 else ''
    percent = f'{arrow}{abs(quote.percent):.2f}%' if quote.percent is not None else '등락률 미확인'
    change = ('+' if direction > 0 else '-' if direction < 0 else '') + integer(abs(direction)) + '원' if quote.change is not None else '—'
    status = '장외' if quote.market_status == 'CLOSE' else domestic_session(quote.fetched_at)
    return (f'{color} {quote.name} 주가 {color}\n'
            f'✔️ 현재가: {integer(quote.price)}원 ({percent})\n'
            f'✔️ 전일대비: {change}\n'
            f'✔️ 거래량: {integer(quote.volume) + "주" if quote.volume is not None else "—"}\n'
            f'✔️ 거래대금: {turnover_text(quote.turnover)}\n'
            f'🕒 {quote.fetched_at.astimezone(KST):%m.%d. %H:%M:%S} 조회 · {status}\n'
            '출처: 한국투자증권 · 통합')


class StockService:
    def __init__(self, cache_dir=None, code_dir=None, data_home=None,
                 codes_loader=None, quote_loader=None, basic_loader=None, monotonic=time.monotonic,
                 us_loader=None):
        self.code_dir = Path(code_dir or os.environ.get('KAKAO_STOCK_CODE_DIR') or Path.home() / 'projects' / 'domino-code')
        self.data_home = Path(data_home or os.environ.get('KAKAO_STOCK_DATA_HOME') or 'C:/domino')
        self.cache_dir = Path(cache_dir or os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'KKanggallbot-stocks'
        self.codes_loader = codes_loader or self._load_codes
        self.quote_loader = quote_loader or self._load_quote
        self.basic_loader = basic_loader or self._load_basic
        self.monotonic = monotonic
        self.us_loader = us_loader or self._load_us
        self.lock = threading.RLock()
        self.codes = {}; self.codes_loaded_at = None; self.quotes = {}; self.client = None
        self.code_names = {}

    def _modules(self):
        if not (self.code_dir / 'domino_kis.py').is_file():
            raise QuoteError('PC의 한투 조회 모듈 설정이 필요합니다.')
        path = str(self.code_dir)
        if path not in sys.path:
            sys.path.insert(0, path)
        return importlib.import_module('domino_kis'), importlib.import_module('domino_stock_performance')

    def _load_codes(self):
        # Reuse public listings only; never read domino.db or holdings.
        path = self.data_home / 'performance_listing_codes.json'
        old = {}
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):raise ValueError('listing cache type')
            old = payload.get('codes', {})
            if not isinstance(old, dict):old = {}
            if payload.get('date') == datetime.now(KST).date().isoformat() and old:
                return old
        except (OSError, ValueError, TypeError):
            pass
        _, public = self._modules()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return public.listing_codes(self.cache_dir) or old

    def _load_basic(self, code):
        response = requests.get('https://m.stock.naver.com/api/stock/' + code + '/basic',
                                headers={'User-Agent': 'Mozilla/5.0 KKanggallbot'}, timeout=8)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('itemCode') != code or data.get('nationType') != 'KOR':
            raise QuoteError('종목 이름 검증 실패')
        return data

    def _load_quote(self, code):
        kis, _ = self._modules()
        if self.client is None:
            self.client = kis.Client(self.data_home)
        return self.client.query(kis.DOMESTIC, {'FID_COND_MRKT_DIV_CODE': 'UN', 'FID_INPUT_ISCD': code})

    def _load_us(self, symbol):
        from .us_quotes import load_us
        kis, _ = self._modules()
        if self.client is None:
            self.client = kis.Client(self.data_home)
        return load_us(self.client, getattr(kis, 'OVERSEAS', None), symbol)

    def _catalog(self):
        if self.codes_loaded_at is None or self.monotonic() - self.codes_loaded_at >= 86400:
            data = self.codes_loader()
            valid = {}
            names = {}
            for name, ticker in data.items():
                if isinstance(ticker, str) and re.fullmatch(r'(?:KRX|KOSDAQ):[A-Z0-9]{6}', ticker):
                    valid.setdefault(normalize(name), set()).add(ticker.split(':')[1])
                    names.setdefault(ticker.split(':')[1], str(name))
            self.codes = valid; self.codes_loaded_at = self.monotonic()
            self.code_names = names
        return self.codes

    def reply(self, arguments):
        keyword = str(arguments).strip()
        if not keyword or len(keyword) > 80 or any(ord(c) < 32 for c in keyword):
            return USAGE
        with self.lock:
            try:
                alias = stock_alias(keyword)
                targets = name_targets(keyword)
                if not alias and (targets or normalize(keyword).endswith('우')):
                    catalog = self._catalog()
                    query = normalize(keyword)
                    found = set(catalog.get(query, set()))
                    recognized = bool(targets)
                    if targets:
                        for target in targets:
                            found.update(catalog.get(normalize(target), set()))
                    elif not found:
                        bases = preferred_bases(keyword)
                        listed_bases = [normalize(base) for base in bases if normalize(base) in catalog]
                        recognized = bool(listed_bases or stock_alias(query[:-1]) or name_targets(query[:-1]))
                        for base in listed_bases:
                            for name, codes in catalog.items():
                                if name.startswith(base) and re.fullmatch(r'(?:[0-9]+)?우[ab]?', name[len(base):]):
                                    found.update(codes)
                    if found or recognized:
                        if not found:
                            return '해당 별명에 대응하는 상장 종목이 없습니다.\n종목명·티커로 입력해 주세요.'
                        if len(found) > 1:
                            return self._candidate_reply(found)
                        code = next(iter(found))
                        alias = ('KR', code, self.code_names[code])
                if alias and alias[0] == 'US':
                    keyword = alias[1]
                if not (alias and alias[0] == 'KR') and re.fullmatch(r'[A-Za-z]{1,6}(?:[.\-/][A-Za-z])?', keyword):
                    from .us_quotes import format_us
                    symbol = us_symbol(keyword)
                    key = 'US:' + symbol
                    now = self.monotonic()
                    cached = self.quotes.get(key)
                    if cached and now - cached[0] < 5:
                        return cached[1]
                    result = format_us(self.us_loader(symbol), symbol, datetime.now(KST))
                    if len(self.quotes) >= 128:
                        self.quotes.pop(next(iter(self.quotes)))
                    self.quotes[key] = (now, result)
                    return result
                if alias and alias[0] == 'KR':
                    code, name = alias[1], alias[2]
                elif re.fullmatch('[A-Z0-9]{6}', keyword.upper()):
                    keyword = keyword.upper()
                    code, name = keyword, keyword
                else:
                    catalog = self._catalog()
                    query = normalize(keyword)
                    found = catalog.get(query, set())
                    if not found:
                        found = {c for n, codes in catalog.items() if n.startswith(query) for c in codes}
                    if not found:
                        found = {c for n, codes in catalog.items() if query in n for c in codes}
                    if not found:
                        return '일치하는 종목을 찾지 못했습니다.\n종목명·티커로 입력해 주세요.'
                    if len(found) > 1:
                        return self._candidate_reply(found)
                    code = next(iter(found))
                    name = self.code_names[code]
                now = self.monotonic(); cached = self.quotes.get(code)
                if cached and now - cached[0] < 5:
                    return format_quote(cached[1])
                basic = {}
                try:
                    basic = self.basic_loader(code)
                except (requests.RequestException, OSError, ValueError, TypeError):
                    pass
                if basic.get('stockName'):
                    name = str(basic['stockName'])
                quote = parse_quote(self.quote_loader(code), code, name, datetime.now(KST))
                if len(self.quotes) >= 128:
                    self.quotes.pop(next(iter(self.quotes)))
                self.quotes[code] = (self.monotonic(), quote)
                return format_quote(quote)
            except Exception as error:
                # Provider exceptions may contain headers/tokens. Never send or log their text.
                LOG.warning('Stock quote unavailable (%s)', type(error).__name__)
                return '한투 주가를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요. 연결 설정은 PC에서 확인해 주세요.'

    def _candidate_reply(self, codes):
        return ('여러 종목이 검색됐습니다.\n종목명·티커로 입력해 주세요.\n\n' +
                '\n'.join('· ' + self.code_names[c] + ' (' + c + ')' for c in sorted(codes)[:5]))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='채팅 전송 없이 한투 주가 응답 확인')
    parser.add_argument('name', nargs='*')
    args = parser.parse_args()
    print(StockService().reply(' '.join(args.name)))
