"""KIS comp-interest benchmark yields. No ECOS/FRED/other provider fallback.

The official schema supplies stck_bsop_date but no guaranteed trade time or
refresh interval. Never call this tick-realtime based on an HTTP success alone.
"""
from datetime import datetime
import re

from .market_data import checked_observation, MarketDataError
from .stock_quotes import number, KST


def public_rows(data):
    rows=[]
    for section in ('output1','output2'):
        values=data.get(section,[])
        if isinstance(values,dict):values=[values]
        if not isinstance(values,list):continue
        for row in values:
            if not isinstance(row,dict):continue
            # This is a PUBLIC market endpoint; still whitelist fields rather
            # than storing/printing any complete broker response or headers.
            rows.append({key:str(row.get(key,'')) for key in (
                'hts_kor_isnm','bcdt_code','bond_mnrt_prpr','bond_mnrt_prdy_vrss',
                'prdy_vrss_sign','stck_bsop_date')})
    return rows


def maturity_key(name):
    normalized=re.sub(r'\s+','',name).upper()
    # KIS actually returns "미국 10년T-NOTE 수익률" and "미국 30년T-BOND".
    # The Latin word boundary belongs only to the English year suffix; applying
    # it to 년 rejects the valid Korean/English compound name.
    match=re.search(r'(?<!\d)0?(2|5|10|30)(?:년|年|(?:YEARS?|YRS?|Y)(?![A-Z]))',normalized)
    if not match:return None
    if re.search(r'미국|美國|美국채|US(?:A)?(?:TREASURY|GOV|BOND)|U\.S\.',normalized):prefix='us'
    elif re.search(r'국고채|한국국채|대한민국국채|KOREA.*(?:GOV|BOND|TREASURY)',normalized):prefix='kr'
    else:return None
    if any(word in normalized for word in ('선물','FUTURE','ETF','회사채','CORPORATE')):return None
    return prefix+match[1]


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
