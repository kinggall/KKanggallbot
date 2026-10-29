"""Public US name search, independent from quote execution and private assets."""
from functools import lru_cache
import re
import unicodedata

from .us_catalog_data import RECORDS, HISTORICAL_ONLY


def normalize_name(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(value)).casefold() if c.isalnum())


def canonical_symbol(symbol):
    return symbol.upper().replace('.', '/')


def short_english_name(name):
    text = re.split(r'\s+(?:Class\s+[A-Z]\b|Common Stock\b|Ordinary Shares\b|American Depositary\b)', name, maxsplit=1)[0]
    text = re.sub(r'\s*\(The\)$', '', text).strip(' ,')
    while True:
        shorter = re.sub(r'\s+(?:Inc\.?|Corp\.?|Corporation|plc|Ltd\.?|Limited|Company|Co\.?)$', '', text).strip(' ,')
        if shorter == text:
            return text
        text = shorter


@lru_cache(maxsize=1)
def indexes():
    records, exact = {}, {}
    for symbol, english, korean, venues, sp500 in RECORDS:
        canonical = canonical_symbol(symbol)
        previous = records.get(canonical)
        if previous:
            english = english if venues else previous[1]
            korean = tuple(dict.fromkeys((*previous[2], *korean)))
            venues = tuple(sorted(set((*previous[3], *venues))))
            sp500 = previous[4] or sp500
        records[canonical] = (canonical, english, korean, venues, sp500)
        names = (english, short_english_name(english), *korean)
        for name in names:
            normalized = normalize_name(name)
            if normalized:
                exact.setdefault(normalized, set()).add(canonical)
    return records, exact


def get_record(symbol):
    return indexes()[0].get(canonical_symbol(symbol))


def english_name(symbol):
    record = get_record(symbol)
    return record[1] if record else ''


def display_name(symbol):
    record = get_record(symbol)
    if record:
        return next((n for n in record[2] if re.search('[가-힣]', n)), record[1])
    return symbol


def find_names(query, exact_only=False):
    records, names = indexes()
    normalized = normalize_name(query)
    if not normalized:
        return []
    exact = names.get(normalized, set())
    if exact or exact_only:
        return sorted(exact)
    prefix = {symbol for name, symbols in names.items() if name.startswith(normalized) for symbol in symbols}
    if prefix:
        return sorted(prefix)
    return sorted({symbol for name, symbols in names.items() if normalized in name for symbol in symbols})


def historical_matches(query):
    normalized = normalize_name(query)
    return [(symbol, name) for symbol, name in HISTORICAL_ONLY if normalized == normalize_name(name)]
