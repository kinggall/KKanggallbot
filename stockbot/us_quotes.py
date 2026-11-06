"""KIS US-only quote adapter. No credentials or private holdings are read here."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .stock_quotes import QuoteError, number, integer, KST
from .aliases import US_NAMES
from .us_catalog import display_name

PATH = '/uapi/overseas-price/v1/quotations/price-detail'
EXCHANGE_NAMES = {'NAS': '나스닥', 'NYS': '뉴욕', 'AMS': '아멕스'}
DAY_EXCHANGES = {'NAS': 'BAQ', 'NYS': 'BAY', 'AMS': 'BAA'}


def is_daymarket(when):
    # Overnight US session runs on Korean weekdays; derive DST from US session.
    korea = when.astimezone(KST)
    # At 09:00 KST in winter the US after-market is still open.
    return korea.weekday() < 5 and us_session(when) == '장외' and 9 <= korea.hour < 18


def load_daymarket(client, endpoint, symbol, regular):
    exchange = regular['exchange']
    venue = DAY_EXCHANGES[exchange]
    result = client.query(overseas_spec(endpoint), {'AUTH': '', 'EXCD': venue, 'SYMB': symbol})
    if not isinstance(result, dict) or result.get('curr') != 'USD' or str(result.get('rsym', '')).upper() not in {p + venue + symbol for p in ('R', 'D')}:
        raise QuoteError('Daymarket symbol/currency mismatch')
    price, close = number(result.get('last')), number(regular.get('last'))
    if price is None or price <= 0 or close is None or close <= 0:
        raise QuoteError('Daymarket price/regular close unavailable')
    return result | {'exchange': exchange, 'rsym': 'D' + exchange + symbol,
                     'base': str(close), 'market_session': 'daymarket'}


def overseas_spec(endpoint):
    """Use the installed Domino OVERSEAS path; its query selects the TR ID."""
    if endpoint != PATH:
        raise QuoteError('Unsupported KIS adapter endpoint specification')
    return endpoint


def load_us(client, endpoint, symbol):
    spec = overseas_spec(endpoint)
    # Quote API exchange codes, not order API codes (NASD/NYSE/AMEX).
    for exchange in ('NAS', 'NYS', 'AMS'):
        try:
            result = client.query(spec, {'AUTH': '', 'EXCD': exchange, 'SYMB': symbol})
        except Exception:
            # Some installed clients raise on a symbol absent from this exchange.
            # Try only the other two US exchanges, never echo provider text.
            continue
        if not isinstance(result, dict):
            continue
        price = number(result.get('last'))
        rsym = str(result.get('rsym', '')).upper()
        if price is not None and price > 0 and rsym == 'D' + exchange + symbol and result.get('curr') == 'USD':
            return result | {'exchange': exchange}
    raise QuoteError('US ticker unavailable')


def us_session(when):
    try:
        local = when.astimezone(ZoneInfo('America/New_York'))
    except ZoneInfoNotFoundError:
        # Windows installations need not have tzdata. US post-2007 DST rules.
        utc = when.astimezone(timezone.utc)
        march = datetime(utc.year, 3, 1, 7, tzinfo=timezone.utc)
        november = datetime(utc.year, 11, 1, 6, tzinfo=timezone.utc)
        start = march + timedelta(days=(6 - march.weekday()) % 7 + 7)
        end = november + timedelta(days=(6 - november.weekday()) % 7)
        local = utc.astimezone(timezone(timedelta(hours=-4 if start <= utc < end else -5)))
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5:
        return '장외'
    if 240 <= minute < 570:
        return '프리마켓'
    if 570 <= minute < 960:
        return '정규장'
    if 960 <= minute < 1200:
        return '애프터마켓'
    return '장외'


def format_us(output, symbol, when):
    if not isinstance(output, dict) or output.get('exchange') not in ('NAS', 'NYS', 'AMS'):
        raise QuoteError('US exchange missing')
    if str(output.get('rsym', '')).upper() != 'D' + output['exchange'] + symbol:
        raise QuoteError('US symbol mismatch')
    if output.get('curr') != 'USD':
        raise QuoteError('US currency mismatch')
    price, previous = number(output.get('last')), number(output.get('base'))
    if price is None or price <= 0:
        raise QuoteError('US price missing')
    change = price - previous if previous is not None and previous > 0 else None
    percent = change / previous * 100 if change is not None else None
    direction = change or 0
    color = '🔴' if direction > 0 else '🔵' if direction < 0 else '⚪'
    arrow = '▲' if direction > 0 else '▼' if direction < 0 else ''
    delta = f'{change:+,.4f}'.rstrip('0').rstrip('.') + ' USD' if change is not None else '—'
    pct = f'{arrow}{abs(percent):.2f}%' if percent is not None else '등락률 미확인'
    volume, turnover = number(output.get('tvol')), number(output.get('tamt'))
    name = US_NAMES.get(symbol) or display_name(symbol)
    label = f'{name} ({symbol})' if name != symbol else symbol
    lines = [f'{color} {label} 주가 {color}',
             f'✔️ 현재가: {price:,.4f}'.rstrip('0').rstrip('.') + f' USD ({pct})',
             ('✔️ 정규장 종가대비: ' if output.get('market_session') == 'daymarket' else '✔️ 전일대비: ') + delta,
             '✔️ 거래량: ' + (integer(volume) + '주' if volume is not None and volume >= 0 else '—'),
             '✔️ 거래대금: ' + (f'{turnover:,.2f} USD' if turnover is not None and turnover >= 0 else '—'),
             f'🕒 {when.astimezone(KST):%m.%d. %H:%M:%S} 조회 · ' + ('데이마켓' if output.get('market_session') == 'daymarket' else us_session(when)),
             '출처: 한국투자증권 · 미국 ' + EXCHANGE_NAMES[output['exchange']]]
    return '\n'.join(lines)
