"""KIS comp-interest benchmark yields. No ECOS/FRED/other provider fallback.

The official schema supplies stck_bsop_date but no guaranteed trade time or
refresh interval. Never call this tick-realtime based on an HTTP success alone.
"""
from datetime import datetime, timedelta
import io
import zipfile
import threading
import time
import re

import requests

from .market_data import checked_observation, MarketDataError
from .stock_quotes import number, KST


def public_rows(data):
    rows=[]
    fields=('hts_kor_isnm','bcdt_code','bond_mnrt_prpr','bond_mnrt_prdy_vrss',
            'prdy_vrss_sign','stck_bsop_date')
    def walk(value,depth=0):
        if depth>8:return
        if isinstance(value,list):
            for child in value:walk(child,depth+1)
        elif isinstance(value,dict):
            # Preserve explicit column groups (name1/value1/date1, etc.). Do
            # not repair shifted data by moving unrelated values into slots.
            suffixes={match[1] for key in value if (match:=re.fullmatch(r'hts_kor_isnm(_?\d*)',str(key)))}
            for suffix in suffixes:
                if all(not isinstance(value.get(key+suffix,''),(dict,list)) for key in fields):
                    rows.append({key:str(value.get(key+suffix,'')) for key in fields})
            for child in value.values():
                if isinstance(child,(dict,list)):walk(child,depth+1)
    for section,value in data.items():
        if re.fullmatch(r'output\d*',str(section)):walk(value)
    return rows


def public_schema(data):
    result={}
    for key,value in data.items():
        if not re.fullmatch(r'output\d*',str(key)):continue
        rows=value if isinstance(value,list) else [value]
        result[key]={'rows':len(rows),'fields':sorted({str(k) for row in rows[:5] if isinstance(row,dict) for k in row})}
    return result


def maturity_key(name):
    normalized=re.sub(r'\s+','',name).upper()
    # KIS actually returns "미국 10년T-NOTE 수익률" and "미국 30년T-BOND".
    # The Latin word boundary belongs only to the English year suffix; applying
    # it to 년 rejects the valid Korean/English compound name.
    match=re.search(r'(?<!\d)0?(2|5|10|30)\s*-?\s*(?:년|年|YEARS?\b|YRS?\b|Y\b)',name.upper())
    if not match:return None
    if re.search(r'미국|美國|美국채|UNITEDSTATES|US(?:A)?(?:TREASURY|GOV|BOND|T-?NOTE|T-?BOND|T-?BILL)|US(?=\d)|U\.S\.',normalized):prefix='us'
    elif re.search(r'국고채|한국국채|대한민국국채|KOREA.*(?:GOV|BOND|TREASURY)',normalized):prefix='kr'
    else:return None
    if any(word in normalized for word in ('선물','FUTURE','ETF','회사채','CORPORATE')):return None
    return prefix+match[1]


MASTER_URL='https://new.real.download.dws.co.kr/common/master/frgn_code.mst.zip'
YIELD_CHART='/uapi/overseas-price/v1/quotations/inquire-daily-chartprice'


def lookup_failure(error):
    """Retain failure stage, never a credential-bearing exception/body/URL."""
    if isinstance(error,requests.HTTPError):
        status=getattr(getattr(error,'response',None),'status_code',None)
        return 'master HTTP '+str(status) if isinstance(status,int) else 'master HTTP error'
    if isinstance(error,requests.Timeout):return 'master download timeout'
    if isinstance(error,requests.ConnectionError):return 'master download connection failure'
    safe={'KIS public master too large','Invalid KIS public bond master',
          'No identified benchmark yields in KIS master','Missing KIS current bond header',
          'KIS bond instrument identity mismatch','KIS bond country/maturity mismatch',
          'Unidentified KIS bond quote name','Invalid KIS current yield',
          'KIS current yield has no matching source date'}
    if isinstance(error,MarketDataError):
        text=str(error)
        if text in safe or re.fullmatch(r'KIS quote unavailable(?: \([A-Z][A-Z0-9]{3,20}\))?',text):return text
    return type(error).__name__


def parse_master(payload,report=None):
    """Official stocks_info/overseas_index_code.py character offsets, CP949.

    No positional repair of the malformed comp-interest rows is attempted.
    API market I is NOT evidence that the file's category character is I.
    """
    if len(payload)>4*1024*1024:raise MarketDataError('KIS public master too large')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info=archive.getinfo('frgn_code.mst')
            if info.file_size>16*1024*1024:raise MarketDataError('KIS public master too large')
            text=archive.read(info).decode('cp949')
    except (zipfile.BadZipFile,KeyError,UnicodeError):
        raise MarketDataError('Invalid KIS public bond master') from None
    found={}
    if report is None:report={}
    report.update({'categories':{},'bond_names':[]})
    for line in text.splitlines():
        if not line:continue
        kind=line[0] if re.fullmatch(r'[A-Za-z0-9]',line[0]) else '?'
        report['categories'][kind]=report['categories'].get(kind,0)+1
        if len(line)<75:continue
        code=line[1:11].strip()
        english=line[11:50].strip()
        korean=line[50:75].strip()
        if not re.fullmatch(r'[A-Za-z0-9.^_:/=+-]{1,10}',code):continue
        names=korean+' '+english
        debt_label=bool(re.search(r'국채|국고|정부채|수익률|TREASUR|T-?(?:BOND|NOTE|BILL)|GOV.*BOND|BOND.*YIELD',names,re.I))
        if debt_label and len(report['bond_names'])<24:
            report['bond_names'].append({'category':kind,'code':code,'name':korean,'english':english})
        korean_key=maturity_key(korean)
        english_key=maturity_key(english)
        if korean_key and english_key and korean_key!=english_key:continue
        key=korean_key or english_key
        abbreviated=bool(re.fullmatch(r'(?:미국|국고채|한국국채)\s*\d+\s*년(?:물)?',korean))
        if key and (debt_label or abbreviated):
            found.setdefault(key,[]).append({'code':code,'name':korean or english,'english':english,'category':kind})
    return found


class BondMaster:
    def __init__(self,get=requests.get,monotonic=time.monotonic):
        self.get=get
        self.monotonic=monotonic
        self.cached=None
        self.loaded=0
        self.retry_after=0
        self.last_failure=''
        self.report={}
        self.lock=threading.Lock()

    def load(self):
        with self.lock:
            tick=self.monotonic()
            if self.cached is not None and tick-self.loaded<86400:return self.cached
            if tick<self.retry_after:raise MarketDataError(self.last_failure)
            try:
                response=self.get(MASTER_URL,timeout=(4,10))
                response.raise_for_status()
                found=parse_master(response.content,self.report)
                if not found:raise MarketDataError('No identified benchmark yields in KIS master')
            except (requests.RequestException,MarketDataError) as error:
                self.retry_after=self.monotonic()+60
                self.last_failure=lookup_failure(error)
                raise MarketDataError(self.last_failure) from None
            self.cached=found;self.loaded=self.monotonic()
            return found


def parse_current_chart(data,key,record,now):
    header=data.get('output1',{})
    if not isinstance(header,dict):raise MarketDataError('Missing KIS current bond header')
    code=str(header.get('stck_shrn_iscd','')).strip()
    if code!=record['code']:raise MarketDataError('KIS bond instrument identity mismatch')
    name=str(header.get('hts_kor_isnm','')).strip()
    response_key=maturity_key(name)
    if response_key and response_key!=key:raise MarketDataError('KIS bond country/maturity mismatch')
    if not response_key and name not in (record['code'],record['name'],record['english']):
        raise MarketDataError('Unidentified KIS bond quote name')
    value=number(header.get('ovrs_nmix_prpr'))
    previous=number(header.get('ovrs_nmix_prdy_clpr'))
    if value is None or not -20<value<100:raise MarketDataError('Invalid KIS current yield')
    # Use the CURRENT output1 value only, never silently fill it with a daily
    # candle close. A matching candle supplies a date, not a tick timestamp.
    samples={}
    for row in data.get('output2',[]):
        try:date=datetime.strptime(str(row.get('stck_bsop_date','')),'%Y%m%d').date()
        except (ValueError,AttributeError):continue
        if now.date()-timedelta(days=14)<=date<=now.date():samples[date]=number(row.get('ovrs_nmix_prpr'))
    if not samples or samples[max(samples)]!=value:raise MarketDataError('KIS current yield has no matching source date')
    return checked_observation(value,previous,max(samples).isoformat(),'한국투자증권')


def complete_yields(data,now,master,query_fn):
    """Fill missing tenors using only official KIS master + KIS current quotes."""
    try:result=parse_yields(data,now)
    except MarketDataError:result={}
    wanted={prefix+str(year) for prefix in ('kr','us') for year in (2,10,30)}
    try:catalog=master.load()
    except MarketDataError as error:
        errors={'master':str(error)}
        report=getattr(master,'report',None)
        if isinstance(report,dict) and report:errors['master_records']=str(report)
        return result,[],errors
    diagnostics=[]
    errors={}
    for key in sorted(wanted):
        candidates=catalog.get(key,[])
        if not candidates:
            errors[key]='No exact country/maturity in KIS public master'
            continue
        # More than one current benchmark may exist; try verified identities
        # in order, bounded to avoid sweeping the broker's entire catalogue.
        for record in candidates[:3]:
            detail={'maturity':key,**record}
            if key in result:detail['table_value']=str(result[key].value)
            diagnostics.append(detail)
            try:
                response=query_fn(YIELD_CHART,{'FID_COND_MRKT_DIV_CODE':'I',
                         'FID_INPUT_ISCD':record['code'],
                         'FID_INPUT_DATE_1':(now-timedelta(days=14)).strftime('%Y%m%d'),
                         'FID_INPUT_DATE_2':now.strftime('%Y%m%d'),'FID_PERIOD_DIV_CODE':'D'})
                observation=parse_current_chart(response,key,record,now)
                detail['current_value']=str(observation.value)
                if key in result:detail['difference_from_table']=str(observation.value-result[key].value)
                if key not in result or observation.as_of>=result[key].as_of:
                    result[key]=observation
                else:detail['kept']='newer_comp_interest_date'
                break
            except Exception as error:
                detail['failure']=lookup_failure(error)
                errors[key]=detail['failure']
        if key in result:errors.pop(key,None)
    return result,diagnostics,errors


def parse_yields(data,now):
    result={}
    for row in public_rows(data):
        key=maturity_key(row['hts_kor_isnm'])
        if key is None:continue
        value=number(row['bond_mnrt_prpr'])
        delta=number(row['bond_mnrt_prdy_vrss'])
        sign=row['prdy_vrss_sign']
        try:date=datetime.strptime(row['stck_bsop_date'],'%Y%m%d').date()
        except ValueError:continue
        if date>now.date() or value is None or not -20<value<100:continue
        previous=None
        if delta is not None and sign in ('1','2','3','4','5'):
            previous=value-abs(delta)*(-1 if sign in ('4','5') else 1)
        observation=checked_observation(value,previous,date.isoformat(),'한국투자증권')
        if key not in result or observation.as_of>result[key].as_of:result[key]=observation
    if not result:raise MarketDataError('KIS comp-interest has no identified KR/US 2/5/10/30Y yields')
    return result
