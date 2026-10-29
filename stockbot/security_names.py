"""Public US security names; never send holdings/account data to the provider."""
import csv
import io
import threading
import time

import requests
from .us_catalog import english_name

URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
KNOWN_NAMES = {'VOO': 'Vanguard S&P 500 ETF'}
# Confirmed US listings; do not infer listing country from profit currency.
# Names remain provider-resolved rather than guessing a historical fund name.
KNOWN_US_SYMBOLS = {'KORU', 'SPCX', *KNOWN_NAMES}


class USSecurityNames:
    def __init__(self, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.names = {}
        self.next_refresh = 0
        self.lock = threading.Lock()

    def __call__(self, symbol):
        catalog_name = english_name(symbol)
        if catalog_name:
            return catalog_name
        with self.lock:
            now = self.monotonic()
            if now >= self.next_refresh:
                try:
                    response = requests.get(URL, timeout=8, headers={'User-Agent': 'Mozilla/5.0 KKanggallbot'})
                    response.raise_for_status()
                    rows = csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')), delimiter='|')
                    if not {'Symbol', 'Security Name', 'Test Issue'}.issubset(rows.fieldnames or []):
                        raise ValueError('Unexpected security directory')
                    names = {row['Symbol']: row['Security Name'].strip() for row in rows
                             if row.get('Test Issue') == 'N' and row.get('Security Name', '').strip()}
                    if not names:
                        raise ValueError('Empty security directory')
                    self.names = names
                    self.next_refresh = now + 86400
                except (requests.RequestException, ValueError, UnicodeError):
                    self.next_refresh = now + 300
            return self.names.get(symbol, KNOWN_NAMES.get(symbol, '종목명 미확인'))
