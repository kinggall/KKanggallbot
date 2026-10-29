"""Read-only KIS futures adapter. A daytime quote is never relabelled night."""
from datetime import datetime, timedelta
import re
import os
import time
from urllib.parse import urlencode

from .market_data import checked_observation, MarketDataError
from .stock_quotes import KST, number

BOARD='/uapi/domestic-futureoption/v1/quotations/display-board-futures'
CHART='/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice'
INDEX='/uapi/domestic-stock/v1/quotations/inquire-index-price'
ENDPOINTS={BOARD:'FHPIF05030200',CHART:'FHKIF03020200',INDEX:'FHPUP02100000'}
HOSTS={'https://openapi.koreainvestment.com:9443','https://openapivts.koreainvestment.com:29443'}


def contract_month(row):
    name=str(row.get('hts_kor_isnm',''))
    match=re.search(r'(?<!\d)(20\d{2}(?:0[1-9]|1[0-2]))(?!\d)',name)
    return match[1] if match else None


def is_kospi200_contract(row, market_class=None):
    code=str(row.get('futs_shrn_iscd',''))
    if re.fullmatch(r'101(?:[A-Z0-9]{3}|[A-Z0-9]{5})',code):return True
    if not re.fullmatch(r'[A-Z0-9]{6,8}',code):return False
    name=re.sub(r'\s+','',str(row.get('hts_kor_isnm',''))).upper()
    if any(word in name for word in ('미니','MINI','스프레드','SPREAD','옵션','OPTION')):return False
    # Standard-board rows may abbreviate the product name to "F YYYYMM".
    # This abbreviation is not sufficient outside the KI board.
    if market_class=='KI' and (re.fullmatch(r'F20\d{2}(?:0[1-9]|1[0-2])',name)
                              or re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])\(F\)',name)):return True
    # New code families are accepted only with the public product name,
    # never because their numeric price resembles the KOSPI200 future.
    return bool(re.match(r'^(?:코스피200|KOSPI200)(?:선물|F)',name))


def query(client,path,params):
    if path not in ENDPOINTS or client.base not in HOSTS:
        raise MarketDataError('Unsupported market endpoint')
    # Keep existing client pacing/token handling, without changing Domino's
    # module or its ALLOWED table and without any order/account endpoint.
    with client.lock:
        client.authenticate()
        wait=client.minimum_interval-(time.monotonic()-client.last_call)
        if wait>0:time.sleep(wait)
        headers={'Content-Type':'application/json; charset=utf-8',
                 'authorization':'Bearer '+client.token,'appkey':client.key,'appsecret':client.secret,
                 'tr_id':ENDPOINTS[path],'custtype':'P'}
        try:
            data=client.send(client.base+path+'?'+urlencode(params),headers)
        finally:
            client.last_call=time.monotonic()
    if not isinstance(data,dict) or str(data.get('rt_cd'))!='0':
        raise MarketDataError('Futures quote unavailable')
    return data


def night_observation(data,code,now):
    basic=data.get('output1',{})
    if basic.get('futs_shrn_iscd')!=code:
        raise MarketDataError('Futures identity mismatch')
    candidates=[]
    for row in data.get('output2',[]):
        try:
            stamp=datetime.strptime(str(row['stck_bsop_date'])+str(row['stck_cntg_hour']).zfill(6),'%Y%m%d%H%M%S').replace(tzinfo=KST)
            if not (stamp.hour>=18 or stamp.hour<6 or (stamp.hour,stamp.minute,stamp.second)==(6,0,0)):continue
            if stamp>now or now-stamp>timedelta(days=7):continue
            price=number(row.get('futs_prpr'))
            if price is not None and price>0:candidates.append((stamp,price))
        except (ValueError,TypeError,KeyError):
            continue
    if not candidates:raise MarketDataError('No confirmed night-session bar')
    stamp,price=max(candidates,key=lambda row:row[0])
    # Current basic quote may be a later day-session value. In that case do not
    # mix its reference close/change with an earlier night bar.
    previous=basic.get('futs_prdy_clpr') if number(basic.get('futs_prpr'))==price and (now.hour>=18 or now.hour<6) else None
    return checked_observation(price,previous,stamp.isoformat(),'한국투자증권 · '+code)


class KISNightFutures:
    def __init__(self,stock_service,now=None,contract=None):
        self.stock_service=stock_service
        self.now=now or (lambda:datetime.now(KST))
        # Pin the explicitly requested delivery month, but resolve its actual
        # instrument code from the live standard board, not a guessed code.
        self.contract=contract or os.environ.get('KAKAO_NIGHT_FUTURES_MONTH','202612')
        if not re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])',self.contract):
            raise MarketDataError('Invalid night futures delivery month')

    def client_instance(self):
        service=self.stock_service
        with service.lock:
            kis,_=service._modules()
            if service.client is None:service.client=kis.Client(service.data_home)
            client=service.client
        return client

    def domestic_index(self,item):
        codes={'kospi':'0001','kosdaq':'1001'}
        if item.key not in codes:raise MarketDataError('Unsupported domestic index')
        data=query(self.client_instance(),INDEX,{'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':codes[item.key]})
        row=data.get('output',{})
        value=number(row.get('bstp_nmix_prpr'))
        delta=number(row.get('bstp_nmix_prdy_vrss'))
        sign=str(row.get('prdy_vrss_sign',''))
        if value is None or value<=0 or delta is None or sign not in ('1','2','3','4','5'):
            raise MarketDataError('Domestic index quote unavailable')
        delta=abs(delta)*(-1 if sign in ('4','5') else 1)
        return checked_observation(value,value-delta,self.now().astimezone(KST).isoformat(),
                                   '한국투자증권')

    def __call__(self):
        client=self.client_instance()
        now=self.now().astimezone(KST)
        board=query(client,BOARD,{'FID_COND_MRKT_DIV_CODE':'F','FID_COND_SCR_DIV_CODE':'20503','FID_COND_MRKT_CLS_CODE':'KI'})
        contracts=[]
        selected=[]
        for row in board.get('output',[]):
            code=str(row.get('futs_shrn_iscd',''))
            days=number(row.get('hts_rmnn_dynu'))
            if is_kospi200_contract(row,'KI') and days is not None and days>=0:
                if days==0 and now.hour>=15:continue
                contracts.append((days,code))
                if contract_month(row)==self.contract:selected.append((days,code))
        if not contracts:
            public_codes=[]
            for row in board.get('output',[]):
                code=str(row.get('futs_shrn_iscd',''))
                if not re.fullmatch(r'[A-Z0-9]{6,12}',code):continue
                name=re.sub(r'[^가-힣A-Za-z0-9 .()/\-]','',str(row.get('hts_kor_isnm','')))[:48]
                public_codes.append(code+(' ('+name+')' if name else ''))
            # Public instrument identifiers only; no response bodies/tokens.
            detail=', '.join(public_codes[:8]) or 'none'
            raise MarketDataError('KOSPI200 front contract unavailable; public codes: '+detail)
        if selected:
            code=min(selected)[1]
        elif now.strftime('%Y%m')<=self.contract:
            raise MarketDataError('Requested KOSPI200 '+self.contract+'(F) contract unavailable on standard board')
        else:
            # After the requested month, roll to a live nearest contract.
            code=min(contracts)[1]
        cutoff=now if now.hour>=18 or now.hour<6 else now.replace(hour=6,minute=0,second=0,microsecond=0)
        data=query(client,CHART,{'FID_COND_MRKT_DIV_CODE':'F','FID_INPUT_ISCD':code,
                                'FID_HOUR_CLS_CODE':'60','FID_PW_DATA_INCU_YN':'Y','FID_FAKE_TICK_INCU_YN':'N',
                                'FID_INPUT_DATE_1':cutoff.strftime('%Y%m%d'),'FID_INPUT_HOUR_1':cutoff.strftime('%H%M%S')})
        return night_observation(data,code,now)
