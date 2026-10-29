"""Read-only KIS futures adapter. A daytime quote is never relabelled night."""
from datetime import datetime, timedelta
import re
import time
from urllib.parse import urlencode

from .market_data import checked_observation, MarketDataError
from .stock_quotes import KST, number

BOARD='/uapi/domestic-futureoption/v1/quotations/display-board-futures'
CHART='/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice'
ENDPOINTS={BOARD:'FHPIF05030200',CHART:'FHKIF03020200'}
HOSTS={'https://openapi.koreainvestment.com:9443','https://openapivts.koreainvestment.com:29443'}


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
    def __init__(self,stock_service,now=None):
        self.stock_service=stock_service
        self.now=now or (lambda:datetime.now(KST))

    def __call__(self):
        service=self.stock_service
        with service.lock:
            kis,_=service._modules()
            if service.client is None:service.client=kis.Client(service.data_home)
            client=service.client
        now=self.now().astimezone(KST)
        board=query(client,BOARD,{'FID_COND_MRKT_DIV_CODE':'F','FID_COND_SCR_DIV_CODE':'20503','FID_COND_MRKT_CLS_CODE':'MKI'})
        contracts=[]
        for row in board.get('output',[]):
            code=str(row.get('futs_shrn_iscd',''))
            days=number(row.get('hts_rmnn_dynu'))
            if re.fullmatch(r'101[A-Z0-9]{3}',code) and days is not None and days>=0:
                if days==0 and now.hour>=15:continue
                contracts.append((days,code))
        if not contracts:raise MarketDataError('KOSPI200 front contract unavailable')
        code=min(contracts)[1]
        cutoff=now if now.hour>=18 or now.hour<6 else now.replace(hour=6,minute=0,second=0,microsecond=0)
        data=query(client,CHART,{'FID_COND_MRKT_DIV_CODE':'F','FID_INPUT_ISCD':code,
                                'FID_HOUR_CLS_CODE':'60','FID_PW_DATA_INCU_YN':'Y','FID_FAKE_TICK_INCU_YN':'N',
                                'FID_INPUT_DATE_1':cutoff.strftime('%Y%m%d'),'FID_INPUT_HOUR_1':cutoff.strftime('%H%M%S')})
        return night_observation(data,code,now)
