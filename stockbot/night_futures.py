"""Read-only KIS futures adapter. A daytime quote is never relabelled night."""
from datetime import datetime, timedelta
import calendar
import re
import os
import time
from urllib.parse import urlencode

from .market_data import checked_observation, MarketDataError
from .stock_quotes import KST, number

BOARD='/uapi/domestic-futureoption/v1/quotations/display-board-futures'
CHART='/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice'
INDEX='/uapi/domestic-stock/v1/quotations/inquire-index-price'
INTEREST='/uapi/domestic-stock/v1/quotations/comp-interest'
YIELD_CHART='/uapi/overseas-price/v1/quotations/inquire-daily-chartprice'
ENDPOINTS={BOARD:'FHPIF05030200',CHART:'FHKIF03020200',INDEX:'FHPUP02100000',INTEREST:'FHPST07020000',YIELD_CHART:'FHKST03030100'}
HOSTS={'https://openapi.koreainvestment.com:9443','https://openapivts.koreainvestment.com:29443'}


def contract_month(row):
    name=str(row.get('hts_kor_isnm',''))
    match=re.search(r'(?<!\d)(20\d{2}(?:0[1-9]|1[0-2]))(?!\d)',name)
    return match[1] if match else None


def is_kospi200_contract(row, market_class=None):
    code=str(row.get('futs_shrn_iscd',''))
    if not re.fullmatch(r'[A-Z0-9]{6,8}',code):return False
    name=re.sub(r'\s+','',str(row.get('hts_kor_isnm',''))).upper()
    if any(word in name for word in ('미니','MINI','스프레드','SPREAD','옵션','OPTION')):return False
    if re.fullmatch(r'101(?:[A-Z0-9]{3}|[A-Z0-9]{5})',code):return True
    # Standard-board rows may abbreviate the product name to "F YYYYMM".
    # This abbreviation is not sufficient outside the KI board.
    if market_class=='' and (re.fullmatch(r'F20\d{2}(?:0[1-9]|1[0-2])',name)
                              or re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])\(F\)',name)):return True
    # New code families are accepted only with the public product name,
    # never because their numeric price resembles the KOSPI200 future.
    return bool(re.match(r'^(?:코스피200|KOSPI200)(?:선물|F)',name))


def next_quarter(month):
    year,month=divmod(int(month[:4])*12+int(month[4:])-1+3,12)
    return f'{year:04d}{month+1:02d}'


def select_contract(rows,now,requested):
    if not rows:raise MarketDataError('Empty standard futures board (market class must be blank)')
    active={}
    expired=set()
    for row in rows:
        if not is_kospi200_contract(row,''):continue
        month=contract_month(row)
        days=number(row.get('hts_rmnn_dynu'))
        if not month or int(month[4:]) not in (3,6,9,12) or days is None:continue
        if days<0 or (days==0 and (now.hour,now.minute)>=(15,45)):
            expired.add(month);continue
        active[month]=str(row['futs_shrn_iscd'])
    target=requested
    while target<now.strftime('%Y%m') or target in expired:target=next_quarter(target)
    if target in active:return active[target]
    # If the expired row has disappeared, the second Thursday is the regular
    # last trading day. Require a live later quarterly contract, never a mini.
    year,month=int(target[:4]),int(target[4:])
    thursdays=[week[calendar.THURSDAY] for week in calendar.monthcalendar(year,month) if week[calendar.THURSDAY]]
    expiry=now.replace(year=year,month=month,day=thursdays[1],hour=15,minute=45,second=0,microsecond=0)
    if now>=expiry:
        target=next_quarter(target)
        later=sorted(m for m in active if m>=target)
        if later:return active[later[0]]
    details=[]
    for row in rows[:8]:
        code=str(row.get('futs_shrn_iscd',''))
        if re.fullmatch(r'[A-Z0-9]{6,12}',code):
            name=re.sub(r'[^가-힣A-Za-z0-9 .()/\-]','',str(row.get('hts_kor_isnm','')))[:48]
            details.append(code+' ('+name+')')
    raise MarketDataError('KOSPI200 '+target+'(F) unavailable; public contracts: '+(', '.join(details) or 'none'))


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
        code=str(data.get('msg_cd','')) if isinstance(data,dict) else ''
        detail=' ('+code+')' if re.fullmatch(r'[A-Z][A-Z0-9]{3,20}',code) else ''
        raise MarketDataError('KIS quote unavailable'+detail)
    return data


def night_observation(data,code,now,night_market=False):
    basic=data.get('output1',{})
    if basic.get('futs_shrn_iscd')!=code:
        raise MarketDataError('Futures identity mismatch')
    candidates=[]
    for row in data.get('output2',[]):
        try:
            day=datetime.strptime(str(row['stck_bsop_date']),'%Y%m%d').replace(tzinfo=KST)
            clock=str(row['stck_cntg_hour']).zfill(6)
            if not re.fullmatch(r'\d{6}',clock):continue
            hour,minute,second=int(clock[:2]),int(clock[2:4]),int(clock[4:])
            if hour>30 or minute>59 or second>59:continue
            stamp=day+timedelta(hours=hour,minutes=minute,seconds=second)
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
    previous=basic.get('futs_prdy_clpr') if number(basic.get('futs_prpr'))==price and (night_market or now.hour>=18 or now.hour<6) else None
    return checked_observation(price,previous,stamp.isoformat(),'한국투자증권 · '+code)


class KISNightFutures:
    def __init__(self,stock_service,now=None,contract=None):
        self.stock_service=stock_service
        self.now=now or (lambda:datetime.now(KST))
        # Resolve actual codes from the board and roll only quarterly months.
        self.contract=contract or os.environ.get('KAKAO_NIGHT_FUTURES_MONTH','202612')
        if not re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])',self.contract):
            raise MarketDataError('Invalid night futures delivery month')
        if int(self.contract[4:]) not in (3,6,9,12):raise MarketDataError('Night futures require a quarterly delivery month')

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

    def yields(self):
        from .kis_yields import public_rows, public_schema, BondMaster, complete_yields
        client=self.client_instance()
        try:
            data=query(client,INTEREST,{'FID_COND_MRKT_DIV_CODE':'I',
                       'FID_COND_SCR_DIV_CODE':'20702','FID_DIV_CLS_CODE':'1','FID_DIV_CLS_CODE1':''})
        except MarketDataError:data={}
        self.public_yield_rows=public_rows(data)
        self.public_yield_schema=public_schema(data)
        if not hasattr(self,'bond_master'):self.bond_master=BondMaster()
        result,self.public_bond_candidates,self.public_yield_errors=complete_yields(
            data,self.now().astimezone(KST),self.bond_master,lambda path,params:query(client,path,params))
        return result

    def __call__(self):
        client=self.client_instance()
        now=self.now().astimezone(KST)
        # Official Postman v2.6: blank=KOSPI200, MKI=mini, KQI=KOSDAQ150.
        # KI is NOT a valid documented value; rt_cd=0 with no rows is possible.
        board=query(client,BOARD,{'FID_COND_MRKT_DIV_CODE':'F','FID_COND_SCR_DIV_CODE':'20503','FID_COND_MRKT_CLS_CODE':''})
        code=select_contract(board.get('output',[]),now,self.contract)
        # Official CM night-session convention: after midnight use 24+ hours
        # and the preceding evening's date (01:30 => 253000, close => 300000).
        session_day=now if now.hour>=18 else now-timedelta(days=1)
        hour=now.hour if now.hour>=18 else now.hour+24 if now.hour<6 else 30
        minute,second=(now.minute,now.second) if now.hour>=18 or now.hour<6 else (0,0)
        data=query(client,CHART,{'FID_COND_MRKT_DIV_CODE':'CM','FID_INPUT_ISCD':code,
                                'FID_HOUR_CLS_CODE':'60','FID_PW_DATA_INCU_YN':'Y','FID_FAKE_TICK_INCU_YN':'N',
                                'FID_INPUT_DATE_1':session_day.strftime('%Y%m%d'),
                                'FID_INPUT_HOUR_1':f'{hour:02d}{minute:02d}{second:02d}'})
        return night_observation(data,code,now,night_market=True)
