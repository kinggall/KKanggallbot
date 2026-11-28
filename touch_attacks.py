"""Reviewed special-attack information; local data and existing ship aliases only."""
import json
from pathlib import Path

DATA = Path(__file__).parent / 'data/touch_attacks.json'


def format_reply(message, ship_ids_for):
    data = json.loads(DATA.read_text(encoding='utf-8'))
    groups = data['groups']
    pieces = message.split(maxsplit=1)
    if len(pieces) == 1:
        lines = ['[터치 종류 · 특수공격]', '!터치 함선명 입력 시,', '편성·조건·배율을 보여줍니다.']
        for group in groups:
            ships = group['overview'].partition(' — ')[0]
            lines += ['', '■ ' + group['title'], '· ' + ships]
        return '\n'.join(lines)
    query = pieces[1].strip()
    ship_ids = set(ship_ids_for(query))
    found = [g for g in groups if ship_ids.intersection(g['flagship_ids'] + g['related_ship_ids'])]
    if not found:
        return '해당 함선의 터치 정보를 찾지 못했습니다.\n!터치로 종류와 사용 가능한 함선을 확인해 주세요.'
    found.sort(key=lambda g: not bool(ship_ids.intersection(g['flagship_ids'])))
    lines = [f'[터치 · {query}]']
    for group in found:
        role = '기함 가능' if ship_ids.intersection(group['flagship_ids']) else '특정 조합의 참여함'
        lines += ['', f"■ {group['title']} · {role}"]
        for section in group['sections']:
            lines += ['', '[' + section['title'] + ']']
            lines += ['· ' + line for line in section['lines']]
        lines += ['', '출처:'] + group['sources']
    lines += ['', f"자료 검수: {data['reviewed_on']}",
              '※ 조건을 갖춰도 확률로 발동합니다. 배율은 최종 피해량이나 발동률을 뜻하지 않습니다.']
    text = '\n'.join(lines)
    if len(text) > 1800:
        text = text.replace('\n', '\u200b' * 4000 + '\n', 1)
    return text
