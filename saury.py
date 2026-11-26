"""User-supplied poi-statistics historical saury rates; commands use a saved snapshot."""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA = Path(__file__).parent / 'data/saury_drops.json'


def format_reply(data=None):
    if data is None:
        data = json.loads(DATA.read_text(encoding='utf-8'))
    lines = ['[꽁치 드랍 확률]' + '\u200b' * 4000, f"✔️ {data['rate_year']}년 기준 (poi-statistics 참고 확률)"]
    last = None
    for row in sorted(data['rows'], key=lambda r: (*map(int, r['map'].split('-')), r['node'])):
        if last != row['map']:
            lines.append('')
            last = row['map']
        s, a = (format(Decimal(row[rank]).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP), '.1f')
                if row[rank] is not None else '?' for rank in ('s', 'a'))
        a_text = f" / A {a}%" if row['a'] is None or Decimal(row['a']) != 0 else ''
        lines.append(f"· {row['map']} {row['node']}: S {s}%{a_text}")
    lines += ['', '[꽁치 유리 장비]']
    for group in data['equipment_groups']:
        lines.append(f"· {group['category']}: {group['text']}")
    lines += ['', '⚠️ 폭뢰투사기는 어장에 피해를 줍니다. 남획 방지를 위해 지속적인 꽁치 파밍에서는 제외하고, 여러 해역을 번갈아 도는 것을 권장합니다.',
              '※ 보유 꽁치 수 등에 따라 실제 드랍률은 달라질 수 있습니다.',
              f"확률 출처: {data['source']}", f"장비 출처: {data['equipment_source']}"]
    return '\n'.join(lines)
