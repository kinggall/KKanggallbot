"""Public KIS market-wide investor net buying; no personal account requests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import threading
import time

from .market_data import MarketDataError, decimal_text
from .night_futures import query, INVESTOR
from .stock_quotes import KST, number


@dataclass(frozen=True)
class FlowMarket:
    key: str
    label: str
    market: str
    sector: str


# Official Postman v2.6 market/sector mapping. Do not include mini/weekly
# options or stock futures under the KOSPI200 futures/options labels.
FLOW_MARKETS=(FlowMarket('kospi','🇰🇷 코스피','KSP','0001'),
              FlowMarket('kosdaq','🇰🇷 코스닥','KSQ','1001'),
              FlowMarket('futures','🇰🇷 선물','K2I','F001'),
              FlowMarket('call','🇰🇷 콜옵션','K2I','OC01'),
              FlowMarket('put','🇰🇷 풋옵션','K2I','OP01'))
ACTORS=(('prsn','개인'),('frgn','외국인'),('orgn','기관'))


@dataclass(frozen=True)
class FlowSnapshot:
    amounts: tuple
    retrieved_at: datetime


def parse_snapshot(data,now):
    rows=data.get('output',[])
    if isinstance(rows,dict):rows=[rows]
    if not isinstance(rows,list):raise MarketDataError('Invalid market flow response')
    candidates=[]
    for row in rows:
        if not isinstance(row,dict):continue
        amounts=[]
        for code,label in ACTORS:
            value=number(row.get(code+'_ntby_tr_pbmn'))
            if value is None:
                buy=number(row.get(code+'_shnu_tr_pbmn'))
                sell=number(row.get(code+'_seln_tr_pbmn'))
                if buy is not None and sell is not None:value=buy-sell
            amounts.append(value)
        if any(value is not None for value in amounts):candidates.append(tuple(amounts))
    # This endpoint is the single current top table, not a time-series sum.
    if len(candidates)!=1:raise MarketDataError('Missing or ambiguous current market flow table')
    return FlowSnapshot(candidates[0],now.astimezone(KST))


class KISFlowLoader:
    def __init__(self,adapter,now=None):
        self.adapter=adapter
        self.now=now or (lambda:datetime.now(KST))

    def __call__(self,market):
        data=query(self.adapter.client_instance(),INVESTOR,
                   {'FID_INPUT_ISCD':market.market,'FID_INPUT_ISCD_2':market.sector})
        return parse_snapshot(data,self.now())


def amount_text(value):
    if value is None:return '미확인'
    # Market-wide investor trade amounts: million KRW -> 100 million KRW.
    amount=value/Decimal(100)
    sign='+' if amount>0 else '-' if amount<0 else ''
    return sign+decimal_text(abs(amount),2,True)


class InvestorFlows:
    def __init__(self,loader,monotonic=time.monotonic):
        self.loader=loader
        self.monotonic=monotonic
        self.cache={}
        self.lock=threading.Lock()

    def load(self,market):
        with self.lock:cached=self.cache.get(market.key)
        if cached and self.monotonic()-cached[0]<(15 if cached[1] is not None else 5):return cached[1]
        try:snapshot=self.loader(market)
        except Exception:snapshot=None
        with self.lock:self.cache[market.key]=(self.monotonic(),snapshot)
        return snapshot

    def reply(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            snapshots=list(executor.map(self.load,FLOW_MARKETS))
        lines=['[투자자 순매수 · 억원]','']
        for market,snapshot in zip(FLOW_MARKETS,snapshots):
            if snapshot is None:
                lines.extend([market.label+': 조회 불가',''])
                continue
            personal,foreign,institution=(amount_text(value) for value in snapshot.amounts)
            lines.extend([market.label,
                          '   개인 '+personal+' / 외국인 '+foreign,
                          '   기관 '+institution,''])
        available=[snapshot for snapshot in snapshots if snapshot]
        if available:
            latest=max(snapshot.retrieved_at for snapshot in available)
            lines.extend(['조회 기준: '+latest.strftime('%Y-%m-%d. %H:%M'),'출처: 한국투자증권'])
        else:lines.append('데이터 연결을 확인해 주세요.')
        return '\n'.join(lines)
