"""Public market indicators. Do not substitute ETFs/cash indices for futures."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
import os
import csv
import io
import re
import threading
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
from .stock_quotes import KST, number


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    symbol: str = ''
    unit: str = ''
    digits: int = 2
    trim: bool = False
    provider: str = 'yahoo'


@dataclass(frozen=True)
class Observation:
    value: Decimal
    previous: object
    as_of: str
    source: str


GROUPS = {
 '국내지수': (Instrument('kospi','🇰🇷 코스피','^KS11'), Instrument('kosdaq','🇰🇷 코스닥','^KQ11'),
              Instrument('kospi200','🇰🇷 코스피200','^KS200')),
 '미국지수': (Instrument('sp500','🇺🇸 S&P500','^GSPC'), Instrument('nasdaq','🇺🇸 나스닥','^IXIC'), Instrument('dow','🇺🇸 다우','^DJI')),
 '나선': (Instrument('nq','🇺🇸 나스닥100 선물','NQ=F'),),
 '야선': (Instrument('night','🇰🇷 KOSPI200 야간선물',provider='kis_night'),),
 '환율': (Instrument('usdkrw','💵 USD/KRW','KRW=X'),Instrument('dxy','💵 달러인덱스','DX-Y.NYB')),
 '상품': (Instrument('gold','🥇 금 선물(USD/oz)','GC=F'), Instrument('silver','🥈 은 선물(USD/oz)','SI=F',digits=3),
          Instrument('wti','🛢️ WTI 선물(USD/배럴)','CL=F'),Instrument('gas','🔥 천연가스 선물(USD/MMBtu)','NG=F',digits=3),
          Instrument('copper','🔩 구리 선물(USD/lb)','HG=F',digits=4)),
 '금리': tuple(Instrument(prefix+str(y),label+f' {y}년',unit='%',digits=3,trim=True,provider='kis_yields')
              for prefix,label in (('kr','🇰🇷 국고채'),('us','🇺🇸 미국채')) for y in (2,10,30)),
 '코인': tuple(Instrument('coin'+s,label,s+'-USD',unit=' USD',digits=4 if s=='XRP' else 2)
             for s,label in (('BTC','₿ 비트코인'),('ETH','💎 이더리움'),('XRP','🪙 리플'))),
}


class MarketDataError(ValueError):
    pass


def checked_observation(value, previous, stamp, source):
    value = number(value)
    previous = number(previous)
    if value is None or not stamp:
        raise MarketDataError('Missing market observation')
    datetime.fromisoformat(stamp.replace('Z','+00:00'))
    return Observation(value, previous, stamp, source)


def decimal_text(value, digits=2, trim=False):
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_UP
        text = f'{value:,.{digits}f}'
    return text.rstrip('0').rstrip('.') if trim and '.' in text else text


def format_line(item, observation):
    price = decimal_text(observation.value,item.digits,item.trim) + item.unit
    previous = observation.previous
    if previous is None:
        changes = '증감 미확인'
    else:
        delta = observation.value - previous
        arrow = '▲' if delta > 0 else '▼' if delta < 0 else ''
        change_unit = '%p' if item.unit == '%' else ''
        absolute = arrow + decimal_text(abs(delta),item.digits,item.trim) + change_unit
        percent = arrow + decimal_text(abs(delta / previous * 100),2) + '%' if previous != 0 else '증감률 미확인'
        changes = absolute + ', ' + percent
    return item.label + ': ' + price + '\n   (' + changes + ')'


class MarketProvider:
    def __init__(self, night_loader=None, get=requests.get, now=None, monotonic=time.monotonic):
        self.get = get
        self.now = now or (lambda:datetime.now(KST))
        self.monotonic = monotonic
        self.night_loader = night_loader
        self.lock = threading.RLock()
        self.batches = {}
        self.ecos_items = None
        self.ecos_loaded = 0
        self.request_lock=threading.Lock()
        self.last_request=0

    def request(self,url,**kwargs):
        with self.request_lock:
            delay=.25-(time.monotonic()-self.last_request)
            if delay>0:time.sleep(delay)
            self.last_request=time.monotonic()
        timeout=kwargs.pop('timeout',(3,7))
        response=self.get(url,timeout=timeout,headers={'User-Agent':'Mozilla/5.0 KKanggallbot'},**kwargs)
        response.raise_for_status()
        return response

    def json(self,url,**kwargs):
        response=self.request(url,**kwargs)
        return response.json()

    def load(self,item):
        if item.provider == 'yahoo':
            if item.key in ('kospi','kosdaq','kospi200') and hasattr(self.night_loader,'domestic_index'):
                try:return self.night_loader.domestic_index(item)
                except Exception:pass
            return self.yahoo(item)
        if item.provider == 'upbit': return self.batch('coins',self.upbit,15)[item.key]
        if item.provider == 'treasury': return self.batch('treasury',self.treasury,600)[item.key]
        if item.provider == 'ecos': return self.ecos(item)
        if item.provider == 'kis_yields' and hasattr(self.night_loader,'yields'):
            values=self.batch('kis_yields',self.night_loader.yields,15)
            if item.key not in values:raise MarketDataError('KIS yield maturity unavailable; no daily-rate fallback')
            return values[item.key]
        if item.provider == 'kis_night' and self.night_loader:
            return self.night_loader()
        raise MarketDataError('Market source unavailable')

    def batch(self,key,loader,ttl):
        with self.lock:
            cached=self.batches.get(key)
            if cached and self.monotonic()-cached[0]<(ttl if cached[1] is not None else 5):
                if cached[1] is None:raise MarketDataError('Market batch temporarily unavailable')
                return cached[1]
            try:data=loader()
            except Exception:
                # A failed batch is shared too: do not repeat a slow four-tenor
                # request four times in one verification/command.
                self.batches[key]=(self.monotonic(),None)
                raise
            self.batches[key]=(self.monotonic(),data)
            return data

    def yahoo(self,item):
        for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
            try:
                data=self.json('https://'+host+'/v8/finance/chart/'+quote(item.symbol,safe=''),
                               params={'interval':'1m','range':'1d'})
                chart=data['chart']
                if chart.get('error'):raise MarketDataError('Chart error')
                meta=chart['result'][0]['meta']
                if meta.get('symbol')!=item.symbol:raise MarketDataError('Market identity mismatch')
                stamp=datetime.fromtimestamp(int(meta['regularMarketTime']),timezone.utc).isoformat()
                previous=meta.get('chartPreviousClose')
                # A one-session request avoids the beginning of a multiday range
                # being misrepresented as the previous trading session close.
                if meta.get('previousClose') is not None:previous=meta['previousClose']
                value=number(meta.get('regularMarketPrice'))
                if value is None or (value<=0 and item.key not in ('wti','gas')):
                    raise MarketDataError('Invalid market price')
                return checked_observation(value,previous,stamp,'Yahoo Finance')
            except (requests.RequestException,ValueError,KeyError,IndexError,TypeError,OverflowError):
                pass
        raise MarketDataError('Public chart unavailable') from None

    def upbit(self):
        rows=self.json('https://api.upbit.com/v1/ticker',params={'markets':'KRW-BTC,KRW-ETH,KRW-XRP'})
        result={}
        for row in rows:
            if row.get('market') not in ('KRW-BTC','KRW-ETH','KRW-XRP'):continue
            stamp=datetime.fromtimestamp(int(row['trade_timestamp'])/1000,timezone.utc).isoformat()
            result['coin'+row['market'][4:]]=checked_observation(row['trade_price'],row.get('prev_closing_price'),stamp,
                                                             '업비트 · 원화 · UTC 0시 대비')
        return result

    def treasury(self):
        # FRED DGS series are official constant-maturity Treasury yields, not
        # bond futures, ETFs, or a proxy maturity such as Yahoo's ^FVX.
        try:
            end=self.now().date()
            response=self.request('https://fred.stlouisfed.org/graph/fredgraph.csv',
                                  params={'id':'DGS2,DGS5,DGS10,DGS30',
                                          'cosd':(end-timedelta(days=21)).isoformat(),
                                          'coed':end.isoformat()},timeout=(5,12))
            result={}
            rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
            for year in (2,5,10,30):
                samples={}
                for row in rows:
                    stamp=row.get('observation_date') or row.get('DATE') or ''
                    try:date=datetime.strptime(stamp,'%Y-%m-%d').date()
                    except ValueError:continue
                    value=number(row.get('DGS'+str(year)))
                    if date<=end and value is not None:samples[stamp]=value
                dates=sorted(samples,reverse=True)
                if len(dates)<2:raise MarketDataError('FRED yield history incomplete')
                result['us'+str(year)]=checked_observation(samples[dates[0]],samples[dates[1]],dates[0],
                                                          '미국 연준 FRED · 일별 공시')
            return result
        except (requests.RequestException,ValueError,KeyError,TypeError):
            return self.treasury_xml()

    def treasury_xml(self):
        samples={y:[] for y in (2,5,10,30)}
        current=self.now().replace(day=1)
        previous_month=current-timedelta(days=1)
        # Monthly feeds are much smaller than the complete annual XML feed.
        for month in (current,previous_month):
            response=None
            for attempt in range(2):
                try:
                    response=self.request('https://home.treasury.gov/resource-center-data-chart-center/interest-rates/pages/xml',
                                          params={'data':'daily_treasury_yield_curve','field_tdr_date_value_month':month.strftime('%Y%m')},timeout=(5,30))
                    break
                except (requests.Timeout,requests.ConnectionError):
                    if attempt:raise MarketDataError('US Treasury connection timed out') from None
            root=ET.fromstring(response.content)
            for entry in root.iter():
                if entry.tag.rsplit('}',1)[-1]!='properties':continue
                fields={child.tag.rsplit('}',1)[-1]:child.text for child in entry}
                stamp=str(fields.get('NEW_DATE') or '')[:10]
                try:datetime.strptime(stamp,'%Y-%m-%d')
                except ValueError:continue
                for y in samples:
                    value=number(fields.get('BC_'+str(y)+'YEAR'))
                    if value is not None:samples[y].append((stamp,value))
            if all(len({r[0] for r in rows})>=2 for rows in samples.values()):break
        result={}
        for y,rows in samples.items():
            by_date=dict(rows)
            dates=sorted(by_date,reverse=True)
            if dates:
                result['us'+str(y)]=checked_observation(by_date[dates[0]],by_date[dates[1]] if len(dates)>1 else None,
                                                      dates[0],'미국 재무부 · 일별 공시')
        return result

    def ecos(self,item):
        # Obtain codes and latest dates from metadata; never guess maturity codes.
        with self.lock:
            if self.ecos_items is None or self.monotonic()-self.ecos_loaded>=3600:
                found={}
                for start in range(1,101,10):
                    data=self.ecos_json('StatisticItemList',start,start+9,'817Y002')
                    section=data.get('StatisticItemList',{})
                    rows=section.get('row',[])
                    if not rows:break
                    for row in rows:
                        name=re.sub(r'\s+','',str(row.get('ITEM_NAME','')))
                        match=re.fullmatch(r'국고채\((2|5|10|30)년\)',name)
                        if match and row.get('CYCLE')=='D':found['kr'+match[1]]=row
                    if len(found)==4 or start+9>=int(section.get('list_total_count',0)):break
                if not found:raise MarketDataError('ECOS maturity metadata unavailable')
                self.ecos_items=found
                self.ecos_loaded=self.monotonic()
            meta=self.ecos_items.get(item.key)
            if not meta:raise MarketDataError('ECOS maturity unavailable')
            code=str(meta['ITEM_CODE'])
            end=datetime.strptime(str(meta['END_TIME']),'%Y%m%d')
        def load():
            start=end-timedelta(days=12)
            data=self.ecos_json('StatisticSearch',1,10,'817Y002','D',start.strftime('%Y%m%d'),end.strftime('%Y%m%d'),code)
            rows=data.get('StatisticSearch',{}).get('row',[])
            values={}
            for row in rows:
                if str(row.get('ITEM_CODE1',code))!=code:continue
                value=number(row.get('DATA_VALUE'))
                if value is not None:
                    stamp=datetime.strptime(str(row['TIME']),'%Y%m%d').date().isoformat()
                    values[stamp]=value
            dates=sorted(values,reverse=True)
            if not dates:raise MarketDataError('ECOS yield unavailable')
            return checked_observation(values[dates[0]],values[dates[1]] if len(dates)>1 else None,
                                       dates[0],'한국은행 ECOS · 일별 공시')
        return self.batch(item.key,load,600)

    def ecos_json(self,service,start,end,*parts):
        api_key=os.environ.get('KAKAO_ECOS_API_KEY','sample')
        path='/'.join(quote(str(v),safe='') for v in (service,api_key,'json','kr',start,end,*parts))
        result=self.json('https://ecos.bok.or.kr/api/'+path)
        if result.get('RESULT',{}).get('CODE') not in (None,'INFO-000'):
            raise MarketDataError('ECOS access unavailable')
        return result


class MarketService:
    def __init__(self,provider=None,monotonic=time.monotonic):
        self.provider=provider or MarketProvider()
        self.monotonic=monotonic
        self.cache={}
        self.lock=threading.Lock()

    def reply(self,command):
        items=GROUPS[command]
        def load(item):
            try:
                with self.lock:cached=self.cache.get(item.key)
                if cached and self.monotonic()-cached[0]<(15 if cached[1] is not None else 5):return item,cached[1]
                observation=self.provider.load(item)
                with self.lock:self.cache[item.key]=(self.monotonic(),observation)
                return item,observation
            except Exception:
                with self.lock:self.cache[item.key]=(self.monotonic(),None)
                return item,None  # No provider exception bodies/keys sent to chat.
        with ThreadPoolExecutor(max_workers=min(3,len(items))) as executor:
            rows=list(executor.map(load,items))
        lines=[format_line(item,value) if value else item.label+': 조회 불가' for item,value in rows]
        if command=='금리':lines=['[국채 금리]','']+lines
        values=[value for item,value in rows if value]
        if values:
            stamps=[]
            for value in values:
                parsed=datetime.fromisoformat(value.as_of.replace('Z','+00:00'))
                label=parsed.astimezone(KST).strftime('%Y-%m-%d. %H:%M') if parsed.tzinfo else parsed.strftime('%Y-%m-%d')
                stamps.append((parsed.replace(tzinfo=KST).timestamp() if not parsed.tzinfo else parsed.timestamp(),label))
            unique=list(dict.fromkeys(label for timestamp,label in sorted(set(stamps))))
            basis=unique[-1]
            lines.extend(['','조회 기준: '+basis,'출처: '+' / '.join(dict.fromkeys(v.source for v in values))])
        else:
            lines.extend(['','데이터 연결을 확인해 주세요.'])
        return '\n'.join(lines)
