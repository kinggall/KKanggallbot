"""Fresh public Korean listing identities for IPO/missing portfolio tickers.

Official KIS masters identify candidates; public stock/basic API validates the
exact company/code. No account, ledger, token, or portfolio data is persisted.
"""
from datetime import datetime
import io
import re
import threading
import time
import zipfile

import requests

from .stock_quotes import KST, normalize


MASTERS=(('kospi_code.mst',228),('kosdaq_code.mst',222))


def parse_listing(payload,filename,tail):
    if len(payload)>8*1024*1024:raise ValueError('Public listing master too large')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        info=archive.getinfo(filename)
        if info.file_size>32*1024*1024:raise ValueError('Public listing master too large')
        text=archive.read(info).decode('cp949').replace('\r\n','\n').replace('\r','\n')
    found={}
    for raw in text.splitlines():
        row=raw+'\n'  # Match official text-mode parser's newline convention.
        if len(row)<=21+tail:continue
        prefix=row[:-tail]
        code,isin,name=prefix[:9].strip(),prefix[9:21].strip(),prefix[21:].strip()
        if re.fullmatch(r'[A-Z0-9]{6}',code) and re.fullmatch(r'KR[A-Z0-9]{10}',isin) and name:
            found.setdefault(normalize(name),set()).add(code)
    return found


class DailyListingLookup:
    def __init__(self,basic_loader,get=requests.get,now=None,monotonic=time.monotonic):
        self.basic_loader=basic_loader
        self.get=get
        self.now=now or (lambda:datetime.now(KST))
        self.monotonic=monotonic
        self.lock=threading.RLock()
        self.catalog=None;self.day=None;self.loaded=0
        self.checked={};self.retry_after=0

    def _catalog(self,today,tick):
        if self.day==today and self.catalog is not None and tick-self.loaded<300:return self.catalog
        if self.day==today and tick<self.retry_after:raise ValueError('Listing retry backoff')
        found={}
        succeeded=0
        for filename,tail in MASTERS:
            try:
                response=self.get('https://new.real.download.dws.co.kr/common/master/'+filename+'.zip',timeout=(4,10))
                response.raise_for_status()
                rows=parse_listing(response.content,filename,tail)
                if not rows:continue
                succeeded+=1
                for name,codes in rows.items():found.setdefault(name,set()).update(codes)
            except (requests.RequestException,ValueError,KeyError,zipfile.BadZipFile):continue
        if self.day!=today:self.checked={}
        self.day=today
        if not succeeded:
            self.catalog=None;self.retry_after=tick+60
            raise ValueError('Public listing unavailable')
        self.catalog=found;self.loaded=tick
        return found

    def __call__(self,name):
        today=self.now().astimezone(KST).date().isoformat()
        tick=self.monotonic();key=normalize(name)
        with self.lock:
            cached=self.checked.get(key)
            if cached and cached[0]==today and (cached[2] or tick-cached[1]<300):return cached[2]
            try:
                codes=self._catalog(today,tick).get(key,set())
                code=next(iter(codes)) if len(codes)==1 else ''
                if code:
                    data=self.basic_loader(code)
                    if (not isinstance(data,dict) or data.get('itemCode')!=code
                        or data.get('nationType')!='KOR' or normalize(data.get('stockName',''))!=key):code=''
            except Exception:code=''
            self.checked[key]=(today,tick,code)
            return code
