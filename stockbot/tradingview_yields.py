"""Public TradingView yield indices, not coupon rates or bond prices.

No session cookies, login, challenge bypass, or fallback to another provider.
Scanner snapshots do not include a confirmed trade timestamp here: as_of is
retrieval time, not a fabricated original quote time. Feed delay is preserved.
"""
from datetime import datetime
import re
import time

import requests

from .market_data import checked_observation, MarketDataError
from .stock_quotes import KST, number


SYMBOLS={prefix+str(year):f'TVC:{country}{year:02d}Y'
         for prefix,country in (('kr','KR'),('us','US')) for year in (2,5,10,30)}
COLUMNS=('close','change_abs','update_mode')
# The documented scanner client uses global + markets=[] for all asset
# classes, and sets markets=[route] on an asset-scoped request. A URL alone
# does not establish the same request scope as that client.
ROUTES=('global','bond','cfd')


def failure_summary(diagnostics,subject='국채'):
    if not isinstance(diagnostics,list) or not diagnostics:return None
    labels={'request timeout':'TradingView 응답 시간 초과',
            'connection/proxy unavailable':'TradingView 네트워크·프록시 연결 실패',
            'invalid scanner response':'TradingView 응답 형식 불일치',
            'request failed':'TradingView 요청 실패',
            'HTTP 401':'TradingView 인증 필요(HTTP 401)',
            'HTTP 403':'TradingView 접근 거절(HTTP 403)',
            'HTTP 429':'TradingView 요청 제한(HTTP 429)'}
    for row in diagnostics:
        if not isinstance(row,dict):continue
        reason=row.get('failure')
        if reason in labels:return labels[reason]
        if isinstance(reason,str) and re.fullmatch(r'HTTP [1-5]\d{2}',reason):return 'TradingView '+reason
    if any(isinstance(row,dict) and row.get('missing') for row in diagnostics):
        reasons={reason for row in diagnostics if isinstance(row,dict)
                 for reason in row.get('missing',{}).values()}
        if 'daily-only feed rejected' in reasons:return 'TradingView 일별 전용 피드 반환(실시간으로 사용하지 않음)'
        if 'unexpected fields' in reasons:return 'TradingView 응답 필드 불일치'
        if 'missing or invalid yield' in reasons:return 'TradingView '+('금리' if subject=='국채' else subject)+' 값 누락'
        counts=[row['scanner']+' '+str(row['matched'])+'건' for row in diagnostics
                if isinstance(row,dict) and row.get('scanner') in ROUTES+('forex',) and isinstance(row.get('matched'),int)]
        return 'TradingView '+subject+' 심볼 미반환'+(' ('+' / '.join(counts)+')' if counts else '')
    return None


def parse_scanner(data,now,symbols=None,bounds=(-20,100)):
    if not isinstance(data,dict) or not isinstance(data.get('data'),list):
        raise MarketDataError('TradingView yield response schema unavailable')
    symbols=SYMBOLS if symbols is None else symbols
    reverse={symbol:key for key,symbol in symbols.items()}
    found={};errors={};modes={}
    for row in data['data']:
        if not isinstance(row,dict) or row.get('s') not in reverse:continue
        key=reverse[row['s']]
        if key in found:
            raise MarketDataError('TradingView returned duplicate yield identities')
        fields=row.get('d')
        if not isinstance(fields,list) or len(fields)!=len(COLUMNS):
            errors[key]='unexpected fields';continue
        value,delta,mode=fields
        value,delta=number(value),number(delta)
        if value is None or not bounds[0]<value<bounds[1]:
            errors[key]='missing or invalid yield';continue
        mode=mode if isinstance(mode,str) and re.fullmatch(r'[A-Za-z0-9_]{1,60}',mode) else 'unknown'
        modes[key]=mode
        if mode in ('endofday','end_of_day','eod'):
            errors[key]='daily-only feed rejected';continue
        if mode=='streaming':source='TradingView'
        elif mode=='delayed_streaming':source='TradingView · 지연 시세'
        elif (match:=re.fullmatch(r'delayed_streaming_(\d+)',mode)):
            seconds=int(match[1])
            delay=f'{seconds//60}분' if seconds%60==0 else f'{seconds}초'
            source='TradingView · '+delay+' 지연'
        else:source='TradingView · 지연 여부 미확인'
        found[key]=checked_observation(value,value-delta if delta is not None else None,
                                       now.astimezone(KST).isoformat(),source)
    for key in symbols:
        if key not in found:errors.setdefault(key,'symbol not returned by this scanner')
    return found,errors,modes


class TradingViewYields:
    def __init__(self,post=requests.post,now=None,monotonic=time.monotonic,
                 symbols=None,routes=None,bounds=(-20,100),family='yields'):
        self.post=post
        self.now=now or (lambda:datetime.now(KST))
        self.public_diagnostics=[]
        self.monotonic=monotonic
        self.blocked_until=0
        self.last_failure=''
        self.symbols=SYMBOLS if symbols is None else symbols
        self.routes=ROUTES if routes is None else routes
        self.bounds=bounds
        self.family=family

    def __call__(self):
        if self.monotonic()<self.blocked_until:
            raise MarketDataError('TradingView '+self.family+' unavailable: '+self.last_failure+'; retry backoff active')
        self.public_diagnostics=[]
        result={}
        for route in self.routes:
            pending=[symbol for key,symbol in self.symbols.items() if key not in result]
            if not pending:break
            diagnostic={'scanner':route}
            self.public_diagnostics.append(diagnostic)
            try:
                response=self.post('https://scanner.tradingview.com/'+route+'/scan',
                    json={'markets':[] if route=='global' else [route],
                          'symbols':{'tickers':pending,'query':{'types':[]}},'columns':list(COLUMNS)},
                    headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json'},timeout=(4,10))
                response.raise_for_status()
                payload=response.json()
                found,errors,modes=parse_scanner(payload,self.now(),self.symbols,self.bounds)
                diagnostic['matched']=sum(1 for row in payload['data']
                                          if isinstance(row,dict) and row.get('s') in pending)
                diagnostic.update({'accepted':sorted(found),
                                   'missing':{key:reason for key,reason in errors.items() if self.symbols[key] in pending},
                                   'update_modes':modes})
                for key,value in found.items():
                    if self.symbols[key] in pending:result[key]=value
            except requests.HTTPError as error:
                status=getattr(getattr(error,'response',None),'status_code',None)
                diagnostic['failure']='HTTP '+str(status) if isinstance(status,int) else 'HTTP error'
                # Do not rotate routes to bypass access refusal/rate limits.
                if status in (401,403,429):
                    try:delay=max(60,int(response.headers.get('Retry-After','60')))
                    except (ValueError,TypeError):delay=60
                    self.last_failure=diagnostic['failure']
                    self.blocked_until=self.monotonic()+delay
                    break
            except requests.Timeout:diagnostic['failure']='request timeout'
            except requests.ConnectionError:
                diagnostic['failure']='connection/proxy unavailable';break
            except requests.RequestException:diagnostic['failure']='request failed';break
            except (ValueError,TypeError):diagnostic['failure']='invalid scanner response'
        if not result:
            reason=next((row['failure'] for row in self.public_diagnostics if 'failure' in row),
                        'no valid yield symbols returned')
            raise MarketDataError('TradingView '+self.family+' unavailable: '+reason) from None
        return result
