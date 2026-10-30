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
         for prefix,country in (('kr','KR'),('us','US')) for year in (2,10,30)}
COLUMNS=('close','change_abs','update_mode')
ROUTES=('bond','cfd')


def parse_scanner(data,now):
    if not isinstance(data,dict) or not isinstance(data.get('data'),list):
        raise MarketDataError('TradingView yield response schema unavailable')
    reverse={symbol:key for key,symbol in SYMBOLS.items()}
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
        if value is None or not -20<value<100:
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
    for key in SYMBOLS:
        if key not in found:errors.setdefault(key,'symbol not returned by this scanner')
    return found,errors,modes


class TradingViewYields:
    def __init__(self,post=requests.post,now=None,monotonic=time.monotonic):
        self.post=post
        self.now=now or (lambda:datetime.now(KST))
        self.public_diagnostics=[]
        self.monotonic=monotonic
        self.blocked_until=0
        self.last_failure=''

    def __call__(self):
        if self.monotonic()<self.blocked_until:
            raise MarketDataError('TradingView yields unavailable: '+self.last_failure+'; retry backoff active')
        self.public_diagnostics=[]
        result={}
        for route in ROUTES:
            pending=[symbol for key,symbol in SYMBOLS.items() if key not in result]
            if not pending:break
            diagnostic={'scanner':route}
            self.public_diagnostics.append(diagnostic)
            try:
                response=self.post('https://scanner.tradingview.com/'+route+'/scan',
                    json={'symbols':{'tickers':pending,'query':{'types':[]}},'columns':list(COLUMNS)},
                    headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json'},timeout=(4,10))
                response.raise_for_status()
                found,errors,modes=parse_scanner(response.json(),self.now())
                diagnostic.update({'accepted':sorted(found),
                                   'missing':{key:reason for key,reason in errors.items() if SYMBOLS[key] in pending},
                                   'update_modes':modes})
                for key,value in found.items():
                    if SYMBOLS[key] in pending:result[key]=value
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
            raise MarketDataError('TradingView yields unavailable: '+reason) from None
        return result
