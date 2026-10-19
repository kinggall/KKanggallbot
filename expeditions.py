"""Offline expedition lookup, verified against wikiwiki and ElectronicObserver.

SPDX-License-Identifier: GPL-3.0-only
Sources, discrepancies and rebuilding instructions: EXPEDITION_DATA.md.
"""
from functools import lru_cache
import json
from pathlib import Path
import re

USAGE = '사용법: !원정 [원정번호]\n예: !원정 B4 / !원정 38'
EXPECTED_CODES = {str(i) for i in range(1, 47)} | {
    f'{letter}{i}' for letter, count in (('A', 6), ('B', 6), ('D', 3), ('E', 2))
    for i in range(1, count + 1)
}
STAT_NAMES = (('firepower', '화력'), ('aa', '대공'), ('asw', '대잠'), ('los', '색적'))
RESOURCE_NAMES = (('fuel', '연료'), ('ammo', '탄약'), ('steel', '강재'), ('bauxite', '보키'))


class ExpeditionCatalog:
    def __init__(self, root):
        data = json.loads((Path(root) / 'data/expeditions.json').read_text(encoding='utf-8'))
        if data.get('schema') != 1:
            raise ValueError('원정 자료 형식 오류')
        self.items = data['expeditions']
        self.validate()

    def validate(self):
        if set(self.items) != EXPECTED_CODES:
            raise ValueError('원정 번호 누락 또는 중복')
        for code, data in self.items.items():
            if not data['name'] or data['minutes'] <= 0 or not 2 <= data['fleet_count'] <= 6:
                raise ValueError(f'원정 기본 조건 오류: {code}')
            if not data['fleet_options'] or data['combat_type'] not in (0, 1, 2):
                raise ValueError(f'원정 편성/교전형 오류: {code}')
            if set(data['stats']) - dict(STAT_NAMES).keys() or any(v <= 0 for v in data['stats'].values()):
                raise ValueError(f'원정 스탯 오류: {code}')
            if any(v < 0 for v in data['resources'].values()):
                raise ValueError(f'원정 자원 오류: {code}')
            if any(not 0 <= item['min'] <= item['max'] for item in data['items']):
                raise ValueError(f'원정 보상 오류: {code}')
            for rule in data['unlocks']['all_of']:
                if rule['kind'] not in ('expedition', 'map', 'quest') or rule['timing'] not in ('normal', 'once', 'monthly'):
                    raise ValueError(f'원정 선행조건 오류: {code}')
                if rule['kind'] == 'expedition' and rule['code'] not in self.items:
                    raise ValueError(f'선행 원정 누락: {code}')
        def visit(code, visiting, visited):
            if code in visiting:
                raise ValueError(f'선행 원정 순환: {code}')
            if code in visited:
                return
            visiting.add(code)
            for rule in self.items[code]['unlocks']['all_of']:
                if rule['kind'] == 'expedition':
                    visit(rule['code'], visiting, visited)
            visiting.remove(code)
            visited.add(code)
        visited = set()
        for code in self.items:
            visit(code, set(), visited)

    def reply(self, query):
        query = query.strip().upper()
        if not re.fullmatch(r'(?:\d{1,2}|[ABDE][1-6])', query):
            return USAGE
        code = str(int(query)) if query.isdigit() else query
        if code not in self.items:
            return USAGE
        data = self.items[code]
        tags = []
        if data['monthly']:
            tags.append('월간')
        if data['combat_type']:
            tags.append(f"교전{data['combat_type']}형")
        if data['drum_type']:
            tags.append('드럼형')
        if data['support']:
            tags.append('지원함대')
        suffix = '(' + '/'.join(tags) + ')' if tags else ''
        hours, minutes = divmod(data['minutes'], 60)
        duration = ' '.join(part for part in (f'{hours}시간' if hours else '', f'{minutes}분' if minutes else '') if part)
        lines = [f"{code}: {data['name']}{suffix}", f'○ 소요시간 - {duration}', '', '[조건]']
        for index, option in enumerate(data['fleet_options']):
            label = '편성' if index == 0 else '또는'
            count_label = '총' if data['fleet_count'] == 6 else '최소'
            total = f" ({count_label} {data['fleet_count']}척)" if index == 0 else ''
            lines.append(f'· {label} {option}{total}')
        if data.get('condition_note'):
            lines.append('· ' + data['condition_note'])
        levels = []
        if data['flagship_level'] is not None:
            levels.append(f"기함 Lv{data['flagship_level']}")
        if data['fleet_level'] is not None:
            levels.append(f"함대 Lv 합 {data['fleet_level']}")
        if levels:
            lines.append('· ' + ' / '.join(levels))
        if data['stats']:
            lines.append('· ' + '/'.join(f'{label} {data["stats"][key]}' for key, label in STAT_NAMES if key in data['stats']))
        if data['drums']:
            lines.append(f"· 드럼통 총 {data['drums']['count']}개 / {data['drums']['ships']}척 이상 장착")
        lines.extend(('', '[보상]'))
        resources = [f'{label} {data["resources"][key]}' for key, label in RESOURCE_NAMES if data['resources'][key]]
        if resources:
            lines.append('· ' + '/'.join(resources))
        if data['items']:
            lines.append('· ' + ' / '.join(f"{item['name']} {item['min']}~{item['max']}" for item in data['items']))
        if not resources and not data['items']:
            lines.append('· 보상 없음(지원함대)')
        lines.extend(('', '[선행조건]'))
        groups = {}
        for rule in data['unlocks']['all_of']:
            label = {'expedition': '', 'map': '해역 ', 'quest': '임무 '}[rule['kind']] + rule['code']
            groups.setdefault(rule['timing'], []).append(label)
        for timing, labels in groups.items():
            suffix = {'normal': '', 'once': ' (최초)', 'monthly': ' (매월)'}[timing]
            lines.append(' + '.join(labels) + suffix)
        return '\n'.join(lines)


@lru_cache(maxsize=1)
def catalog():
    return ExpeditionCatalog(Path(__file__).parent)
