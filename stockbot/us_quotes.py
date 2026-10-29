"""KIS US-only quote adapter. No credentials or private holdings are read here."""
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .stock_quotes import QuoteError, number, integer, KST

PATH = '/uapi/overseas-price/v1/quotations/price'
TR_ID = 'HHDFS00000300'


def overseas_spec(domestic):
    """Retain the installed adapter's spec type, replace only endpoint/TR ID.

    Reject unknown adapter layouts instead of accidentally querying a domestic
    endpoint with foreign parameters. No modification to the Domino module.
    """
    changed = set()

    def convert(value):
        if isinstance(value, str):
            if value == '/uapi/domestic-stock/v1/quotations/inquire-price':
                changed.add('path')
                return PATH
            if value == 'FHKST01010100':
                changed.add('tr')
                return TR_ID
            return value
        if is_dataclass(value) and not isinstance(value, type):
            return replace(value, **{f.name: convert(getattr(value, f.name)) for f in fields(value) if f.init})
        if isinstance(value, dict):
            return {key: convert(v) for key, v in value.items()}
        if isinstance(value, tuple):
            items = [convert(v) for v in value]
            return type(value)(*items) if hasattr(value, '_fields') else tuple(items)
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    result = convert(domestic)
    if changed != {'path', 'tr'}:
        raise QuoteError('Unsupported KIS adapter endpoint specification')
    return result


def load_us(client, domestic, symbol):
    spec = overseas_spec(domestic)
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
        if price is not None and price > 0 and rsym == 'D' + exchange + symbol:
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
        return '장외 · 최근 시세'
    if 240 <= minute < 570:
        return '프리마켓'
    if 570 <= minute < 960:
        return '정규장'
    if 960 <= minute < 1200:
        return '애프터마켓'
    return '장외 · 최근 시세'


def format_us(output, symbol, when):
    if not isinstance(output, dict) or output.get('exchange') not in ('NAS', 'NYS', 'AMS'):
        raise QuoteError('US exchange missing')
    if str(output.get('rsym', '')).upper() != 'D' + output['exchange'] + symbol:
        raise QuoteError('US symbol mismatch')
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
    lines = [f'{color} {symbol} 주가 {color}',
             f'✔️ 현재가: {price:,.4f}'.rstrip('0').rstrip('.') + f' USD ({pct})',
             '✔️ 전일대비: ' + delta,
             '✔️ 거래량: ' + (integer(volume) + '주' if volume is not None and volume >= 0 else '—'),
             '✔️ 거래대금: ' + (f'{turnover:,.2f} USD' if turnover is not None and turnover >= 0 else '—'),
             f'🕒 {when.astimezone(KST):%m.%d. %H:%M:%S} 조회 · {us_session(when)}',
             '출처: 한국투자증권 · 미국 ' + output['exchange'],
             '※ 시간대 기준입니다. 지연 시세·휴장·장외 시세 제공 여부는 별도 확인이 필요합니다.']
    return '\n'.join(lines)
