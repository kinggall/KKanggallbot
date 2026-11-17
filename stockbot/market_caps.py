"""KIS public KRX market-cap rankings, including preferred shares."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
import threading
import time

from .market_data import MarketDataError
from .night_futures import MARKET_CAP, query
from .stock_quotes import KST, number

MARKETS = (('kospi', '코스피', '0001', '🔴'), ('kosdaq', '코스닥', '1001', '🔵'))
NUMBERS = ('1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣')


@dataclass(frozen=True)
class CapRow:
    rank: int
    code: str
    name: str
    market_cap: Decimal
    percent: object


@dataclass(frozen=True)
class CapSnapshot:
    rows: tuple
    retrieved_at: datetime


def parse_snapshot(data, now):
    rows = data.get('output') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise MarketDataError('Invalid KIS market-cap ranking response')
    ranked = {}
    codes = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        rank_text = str(row.get('data_rank', '')).strip()
        if not rank_text.isascii() or not rank_text.isdigit() or not 1 <= int(rank_text) <= 8:
            continue
        rank = int(rank_text)
        code = str(row.get('mksc_shrn_iscd', '')).strip()
        name = ' '.join(str(row.get('hts_kor_isnm') or '').split())
        cap = number(row.get('stck_avls'))
        if rank in ranked or code in codes or not re.fullmatch(r'[0-9A-Z]{6}', code) or not name or cap is None or cap <= 0:
            raise MarketDataError('Invalid or duplicate KIS market-cap rank')
        rate = number(row.get('prdy_ctrt'))
        sign = str(row.get('prdy_vrss_sign', ''))
        percent = (abs(rate) if sign in ('1', '2') else -abs(rate) if sign in ('4', '5')
                   else Decimal(0) if sign == '3' and rate == 0 else None) if rate is not None else None
        ranked[rank] = CapRow(rank, code, name, cap, percent)
        codes.add(code)
    if set(ranked) != set(range(1, 9)):
        raise MarketDataError('KIS market-cap top eight is incomplete')
    return CapSnapshot(tuple(ranked[i] for i in range(1, 9)), now.astimezone(KST))


class KISMarketCapLoader:
    def __init__(self, adapter, now=None):
        self.adapter = adapter
        self.now = now or (lambda: datetime.now(KST))

    def __call__(self, market):
        if market not in MARKETS:
            raise MarketDataError('Unsupported market-cap market')
        # Official open-trading-api market_cap: full common/preferred universe,
        # no price or volume cutoffs. Each exchange gets its own ranking.
        data = query(self.adapter.client_instance(), MARKET_CAP, {
            'fid_cond_mrkt_div_code': 'J', 'fid_cond_scr_div_code': '20174',
            'fid_input_iscd': market[2], 'fid_div_cls_code': '0',
            'fid_trgt_cls_code': '0', 'fid_trgt_exls_cls_code': '0',
            'fid_input_price_1': '', 'fid_input_price_2': '', 'fid_vol_cnt': '',
        })
        return parse_snapshot(data, self.now())


def percent_text(value):
    if value is None:
        return '등락률 미확인'
    mark = '🔺' if value > 0 else '▼' if value < 0 else ''
    return f'{mark}{abs(value):.2f}%'


class MarketCaps:
    def __init__(self, loader, monotonic=time.monotonic):
        self.loader, self.monotonic = loader, monotonic
        self.cache = {}
        self.locks = {market[0]: threading.Lock() for market in MARKETS}

    def load(self, market):
        with self.locks[market[0]]:
            cached = self.cache.get(market[0])
            if cached and self.monotonic() - cached[0] < (15 if cached[1] is not None else 5):
                return cached[1]
            try:
                snapshot = self.loader(market)
            except Exception:
                snapshot = None
            self.cache[market[0]] = (self.monotonic(), snapshot)
            return snapshot

    def reply(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            snapshots = list(executor.map(self.load, MARKETS))
        available = [s for s in snapshots if s is not None]
        lines = ['🔥 한국시장 시총 Top 8 🔥']
        if available:
            latest = max(s.retrieved_at for s in available)
            day = '월화수목금토일'[latest.weekday()]
            lines.append(f'🕰️ 조회: {latest:%m-%d}({day}) {latest.hour}시 {latest:%M분 %S초}')
        lines.append('━━━━━━━━━━━━━━')
        for market, snapshot in zip(MARKETS, snapshots):
            lines.extend(['', f'{market[3]} << {market[1]} Top 8 >> {market[3]}', ''])
            if snapshot is None:
                lines.append('조회 불가')
                continue
            for row in snapshot.rows:
                lines.append(f'{NUMBERS[row.rank - 1]} {row.name} ({percent_text(row.percent)})')
        lines.extend(['', '출처: 한국투자증권' if available else '데이터 연결을 확인해 주세요.'])
        return '\n'.join(lines)
