"""Collect Akashi List's saury rates, preserving the stated statistical year."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://akashi-list.me/'
EXPECTED_COUNTS = {'1-1':2, '1-2':2, '1-3':1, '1-4':4, '1-5':3, '1-6':3,
                   '3-1':1, '3-2':3, '3-3':3, '3-4':3, '3-5':2, '7-4':3, '6-1':3, '6-5':5}
GROUPS = [
    ('탐조등', '탐조등 / 96식 150cm 탐조등(★8 이상 효과 증가)', [74, 140]),
    ('소나', '3식 수중탐신의·개 / Type124 ASDIC 계열', [47, 438, 260]),
    ('견시원', '숙련견시원 / 수뢰전대 숙련견시원', [129, 412]),
    ('함재기', '영식 수상정찰기 계열 / 즈이운 계열 / Swordfish 계열', [25, 26, 242]),
    ('대형비행정', '2식 대정 / PBY-5A Catalina', [138, 178]),
    ('회전익기·대잠초계기', '카호 관측기 / 3식 지휘연락기(대잠)', [69, 70]),
    ('항공요원', '야간작전항공요원 / 야간작전항공요원＋숙련갑판원', [258, 259]),
    ('폭뢰', '94식·3식 폭뢰투사기 (어장 피해 주의)', [44, 45]),
    ('보급품', '전투식량 / 꽁치 통조림 (약간의 효과)', [145, 150]),
]


def parse_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.select_one('#saury-content')
    if content is None:
        raise ValueError('Missing saury section')
    basis = next((a for a in content.select('a[href]') if re.search(r'event-sanma\d{4}/', a['href'])), None)
    if basis is None or 'ドロップ確率は' not in content.get_text():
        raise ValueError('Unconfirmed probability basis')
    rate_year = int(re.search(r'event-sanma(\d{4})/', basis['href'])[1])
    title = content.select_one('.rice-map-title').get_text(' ', strip=True)
    rows, layout = [], {}
    for m in content.select('.map-slider > .map'):
        rates = m.select('.per')
        if not rates:
            continue
        name = m.select_one('.map-name').get_text(strip=True)
        icons = m.select('.map-icon.fish')
        if name not in EXPECTED_COUNTS or len(rates) != EXPECTED_COUNTS[name] or len(icons) != len(rates):
            raise ValueError(f'Unreviewed saury map layout: {name}')
        layout[name] = [i.get('style', '') for i in icons]
        for position, rate in enumerate(rates):
            values = re.fullmatch(r'S:\s*([\d.]+|\?)%\s*A:\s*([\d.]+|\?)%', rate.get_text(' ', strip=True))
            if not values:
                raise ValueError(f'Unrecognized probability: {name}/{position}')
            pair = [None if v == '?' else v for v in values.groups()]
            if any(v is not None and not 0 <= float(v) <= 100 for v in pair):
                raise ValueError('Probability outside 0..100')
            rows.append(dict(map=name, position=position, icon_style=layout[name][position], s=pair[0], a=pair[1]))
    if set(layout) != set(EXPECTED_COUNTS):
        raise ValueError('Missing expected saury maps')
    # Preserve source equipment evidence; do not interpret ordinary combat stats as fishing bonuses.
    equipment = []
    for w in content.select('.rice-weapons .weapon'):
        equipment.append({'id': int(w['wid'][1:]), 'name_jp': w.select_one('img[alt]')['alt'],
                          'notes_jp': [n.get_text(' ', strip=True) for n in w.select('.star-up, .minus')],
                          'slight_effect': '若干効果アリ' in w.get_text()})
    if {w['id'] for w in equipment} != {i for _, _, ids in GROUPS for i in ids}:
        raise ValueError('Equipment list changed; review Korean groups')
    if {w['id'] for w in equipment if '漁場ダメージ' in w['notes_jp']} != {44,45}:
        raise ValueError('Fishery damage notes changed')
    return dict(schema=1, source=URL, source_title=title, rate_year=rate_year,
                rate_source=basis['href'], rows=rows, layout=layout, equipment_source=equipment,
                equipment_groups=[dict(category=c, text=t, equipment_ids=ids) for c,t,ids in GROUPS])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, help='Previously downloaded Akashi List HTML')
    parser.add_argument('--output', type=Path, default=ROOT/'data/saury_source.json')
    args = parser.parse_args()
    if args.html:
        payload = args.html.read_bytes()
    else:
        response = requests.get(URL, timeout=(10,30), headers={'User-Agent':'KKanggallbot/1.0'})
        response.raise_for_status()
        payload = response.content
    data = parse_page(payload.decode('utf-8'))
    # A positional source has no machine-readable node letters. Refuse moved icons.
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding='utf-8'))
        if previous['layout'] != data['layout']:
            raise ValueError('Icon positions changed; review node mapping before replacing data')
    data.update(collected_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                source_sha256=hashlib.sha256(payload).hexdigest())
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    temp.replace(args.output)
    print(f"Collected {len(data['rows'])} positions / {len(data['layout'])} maps; rates from {data['rate_year']}")


if __name__ == '__main__':
    main()
