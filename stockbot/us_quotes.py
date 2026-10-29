"""KIS US-only quote adapter. No credentials or private holdings are read here."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .stock_quotes import QuoteError, number, integer, KST
from .aliases import US_NAMES

PATH = '/uapi/overseas-price/v1/quotations/price-detail'
EXCHANGE_NAMES = {'NAS': '나스닥', 'NYS': '뉴욕', 'AMS': '아멕스'}


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
    label = f'{US_NAMES[symbol]} ({symbol})' if symbol in US_NAMES else symbol
    lines = [f'{color} {label} 주가 {color}',
             f'✔️ 현재가: {price:,.4f}'.rstrip('0').rstrip('.') + f' USD ({pct})',
             '✔️ 전일대비: ' + delta,
             '✔️ 거래량: ' + (integer(volume) + '주' if volume is not None and volume >= 0 else '—'),
             '✔️ 거래대금: ' + (f'{turnover:,.2f} USD' if turnover is not None and turnover >= 0 else '—'),
             f'🕒 {when.astimezone(KST):%m.%d. %H:%M:%S} 조회 · {us_session(when)}',
             '출처: 한국투자증권 · 미국 ' + EXCHANGE_NAMES[output['exchange']]]
    return '\n'.join(lines)
