"""Reviewed stock search aliases. Public names only, no portfolio data."""
import re
import unicodedata


def key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


# market, provider symbol, canonical display name, alternative names.
STOCKS = (
    ('KR', '005930', '삼성전자', ('삼전',)),
    ('KR', '034020', '두산에너빌리티', ('두에빌',)),
    ('KR', '005380', '현대차', ('현차', '현대자동차')),
    ('US', 'AAPL', '애플', ('애플',)),
    ('US', 'GOOGL', '알파벳 A', ('구글', '알파벳', '알파벳a', '구글a')),
    ('US', 'GOOG', '알파벳 C', ('알파벳c', '구글c')),
    ('US', 'BRK/B', '버크셔 해서웨이 B', ('버크셔', '버크셔해서웨이', '버크셔b', '버크셔해서웨이b')),
    ('US', 'BRK/A', '버크셔 해서웨이 A', ('버크셔a', '버크셔해서웨이a')),
    ('US', 'TSLA', '테슬라', ('테슬라',)),
    ('US', 'NVDA', '엔비디아', ('엔비디아', '엔비디아주식')),
    ('US', 'MSFT', '마이크로소프트', ('마이크로소프트', '마소')),
    ('US', 'AMZN', '아마존', ('아마존',)),
    ('US', 'META', '메타', ('메타', '메타플랫폼스', '페이스북')),
)
ALIASES = {}
US_NAMES = {}
for market, symbol, name, alternatives in STOCKS:
    for alias in (name, *alternatives):
        normalized = key(alias)
        target = (market, symbol, name)
        if normalized in ALIASES and ALIASES[normalized] != target:
            raise ValueError('Duplicate stock alias')
        ALIASES[normalized] = target
    if market == 'US':
        US_NAMES[symbol] = name


def lookup(value):
    return ALIASES.get(key(value))


def us_symbol(value):
    symbol = value.upper()
    # KIS US quote master uses slashes for Berkshire share classes.
    if re.fullmatch(r'BRK[.\-/][AB]', symbol):
        return symbol[:3] + '/' + symbol[-1]
    return symbol
