"""Reviewed special-attack information; local data and existing ship aliases only."""
import json
from pathlib import Path

DATA = Path(__file__).parent / 'data/touch_attacks.json'


def format_reply(message, ship_ids_for):
    data = json.loads(DATA.read_text(encoding='utf-8'))
    groups = data['groups']
    pieces = message.split(maxsplit=1)
    if len(pieces) == 1:
        lines = ['[터치 종류 · 특수공격]', '!터치 [기함명]', '해당 함선을 기함으로 편성했을 때의 조건·배율을 보여줍니다.']
        for group in groups:
            ships = group['overview'].partition(' — ')[0]
            lines += ['', '■ ' + group['title'], '· ' + ships]
        return '\n'.join(lines)
    query = pieces[1].strip()
    ship_ids = set(ship_ids_for(query))
    found = []
    for group in groups:
        for view in group['flagship_views']:
            if ship_ids.intersection(view['ship_ids']):
                found.append(dict(view))
    if not found:
        return '해당 함선을 기함으로 사용할 수 있는 터치 정보를 찾지 못했습니다.\n!터치로 기함 목록을 확인해 주세요.'
    lines = [f'[터치 · {query} 기함 기준]']
    for group in found:
        lines += ['', f"■ {group['title']}"]
        for table in group['tables']:
            lines += ['', '[' + table['title'] + ']', ' │ '.join(table['headers'])]
            lines += [' │ '.join(row) for row in table['rows']]
            lines += table.get('notes', [])
    lines += ['', f"자료 검수: {data['reviewed_on']}"]
    text = '\n'.join(lines)
    if len(text) > 1800:
        text = text.replace('\n', '\u200b' * 4000 + '\n', 1)
    return text
