"""Pure JSON extraction and net-return calculation matching Domino overview.

Never execute downloaded JavaScript. Private data is kept in memory only.
"""
import json
import re
from decimal import Decimal
from .stock_quotes import number


def embedded_json(html, pattern):
    matches = list(re.finditer(pattern, html))
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous overview JSON')
    value, _ = json.JSONDecoder().raw_decode(html[matches[0].end():])
    if not isinstance(value, dict):
        raise ValueError('Invalid overview JSON')
    return value


def total_profit(html):
    data = embedded_json(html, r'\bconst\s+DATA\s*=\s*')
    market = embedded_json(html, r'window\.DOMINO_SNAPSHOT_QUOTES\s*=\s*')
    quotes = {q['ticker']: q for q in market['quotes']}
    fx = number(quotes.get('CURRENCY:USDKRW', {}).get('price'))
    fx = fx if fx is not None and fx > 0 else None
    zero = Decimal(0)

    def required(value):
        result = number(value)
        if result is None:
            raise ValueError('Overview input unavailable')
        return result

    def money(row):
        amount = required(row.get('amount'))
        if row.get('currency') == 'KRW':
            return amount
        if row.get('currency') == 'USD' and fx:
            return amount * fx
        raise ValueError('Overview currency conversion unavailable')

    total, count = zero, 0
    for account in data['accounts']:
        aid = account['id']
        hs = [h for h in data['holdings'] if h['account_id'] == aid]
        cash = [r for r in data['cash'] if r['account_id'] == aid]
        others = [r for r in data.get('other_assets', []) if r['account_id'] == aid]
        flow = data['net_return'].get(aid, {})
        if not flow.get('has_records') and not hs and not any(r.get('amount') for r in cash + others):
            continue
        if not flow.get('available') or flow.get('issues'):
            raise ValueError('Overview net return incomplete')
        ending = sum((money(r) for r in cash + others), zero)
        exclusion = zero
        for h in hs:
            q = quotes.get(data['symbol_map'].get(h['name']), {})
            price, qty, offer = number(q.get('price')), number(h.get('quantity')), number(h.get('ipo_offer_price'))
            valid = (not h.get('unlisted') and q.get('currency') == h.get('currency')
                     and price is not None and price > 0 and qty is not None and qty > 0)
            ipo = (not h.get('unlisted') and h.get('currency') == 'KRW'
                   and offer is not None and offer > 0 and qty is not None and qty > 0
                   and (not valid or q.get('stale') or q.get('error')))
            valued = (ipo or valid and not q.get('stale') and not q.get('error')) and (h['currency'] == 'KRW' or fx)
            if valued:
                ending += (offer if ipo else price) * qty * (fx if h['currency'] == 'USD' else 1)
            else:
                exclusion += required(h.get('purchase') if h['currency'] == 'KRW' else h.get('cost_krw'))
        principal = (required(flow.get('opening')) + required(flow.get('deposits'))
                     + required(flow.get('stock_in')) - required(flow.get('withdrawals'))
                     - required(flow.get('stock_out')) - exclusion)
        total += ending - principal
        count += 1
    if not count:
        raise ValueError('Overview net return unavailable')
    return total
