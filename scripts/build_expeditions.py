"""Extract expedition facts from a user-supplied wikiwiki HAR and verify EO data.

Usage: python scripts/build_expeditions.py HAR EO_CHECKOUT DATA_CHECKOUT
Prints {catalog, verification} JSON; requires beautifulsoup4 only when rebuilding.
No browser requests or HAR cookies/headers are retained.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from bs4 import BeautifulSoup

WIKI = 'https://wikiwiki.jp/kancolle/%E9%81%A0%E5%BE%81'
CODE = re.compile(r'(?:\d{1,2}|[ABDE][1-6])\Z')
STATS = {'火力': 'firepower', '対空': 'aa', '対潜': 'asw', '索敵': 'los'}
ITEMS = {
    '高速修復材': ('InstantRepair', '수복재'),
    '高速建造材': ('InstantConstruction', '건조재'),
    '開発資材': ('DevelopmentMaterial', '자재'),
    '改修資材': ('ImproveMaterial', '나사'),
    '家具箱(小)': ('FurnitureBoxSmall', '가구함(소)'),
    '家具箱(中)': ('FurnitureBoxMedium', '가구함(중)'),
    '家具箱(大)': ('FurnitureBoxLarge', '가구함(대)'),
    '給糧艦「伊良湖」': ('MoraleFoodIrako', '이라코'),
}


def normalize_code(code):
    return str(int(code)) if code.isdigit() else code.upper()


def text(node):
    return node.get_text(' ', strip=True)


def clean(node):
    node = copy.copy(node)
    for removed in node.select('del, s, .annotation'):
        removed.decompose()
    return text(node)


def source(path, root):
    return {
        'file': str(path.relative_to(root)),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
    }


def parse_wiki(html):
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    unlock_table = next(t for t in tables if '開放要件' in text(t) and any(
        a.get('href') == '#id01' for a in t.find_all('a')))
    unlocks = {}
    previous = None
    for row in unlock_table.find_all('tr'):
        cells = row.find_all(['th', 'td'], recursive=False)
        if len(cells) != 3 or not CODE.fullmatch(text(cells[0])):
            continue
        code = normalize_code(text(cells[0]))
        raw = text(cells[2])
        if raw == '同上':
            if previous is None:
                raise ValueError('Missing previous prerequisite')
            rules = copy.deepcopy(previous)
        else:
            rules = []
            repeat = 'monthly' if '毎月' in raw else 'normal'
            for anchor in cells[2].find_all('a'):
                match = re.fullmatch(r'#id(\d+|[ABDE]\d)', anchor.get('href', ''))
                if match:
                    target = normalize_code(match[1])
                    timing = ('once' if target in ('40', '41') else 'monthly') if code == '44' else repeat
                    rules.append({'kind': 'expedition', 'code': target, 'timing': timing})
            for map_code in re.findall(r'出撃海域\((\d-\d)\)', raw):
                rules.insert(0, {'kind': 'map', 'code': map_code, 'timing': 'normal'})
            for quest_code in re.findall(r'任務\(([A-Z]\d+)\)', raw):
                rules.append({'kind': 'quest', 'code': quest_code, 'timing': 'normal'})
            if not rules or ('または' in raw or 'いずれか' in raw):
                raise ValueError(f'Unrecognized prerequisite structure: {code}: {raw}')
            previous = rules
        unlocks[code] = {'all_of': rules, 'source_text': raw}

    detail_table = next(t for t in tables if '必要旗艦Lv' in text(t) and t.find('a', attrs={'name': 'idE1'}))
    rows = detail_table.find_all('tr')
    details = {}
    for i, row in enumerate(rows):
        cells = row.find_all(['th', 'td'], recursive=False)
        if not cells or cells[0].get('rowspan') != '3' or not CODE.fullmatch(text(cells[0])):
            continue
        code = normalize_code(text(cells[0]))
        if code in details:
            raise ValueError('Duplicate expedition detail')
        level_row = rows[i + 1].find_all(['th', 'td'], recursive=False)
        condition = clean(rows[i + 2])
        levels = [int(n) for n in re.findall(r'Lv\s*(\d+)', text(level_row[0]))]
        h, m, sec = map(int, text(cells[4]).split(':'))
        if sec:
            raise ValueError('Unexpected non-minute duration')
        reward_text = text(level_row[1]).replace(' ', '').replace('（', '(').replace('）', ')')
        resources = {key: int(match[1]) if (match := re.search(label + r'×(\d+)', reward_text)) else 0
                     for label, key in [('燃料', 'fuel'), ('弾薬', 'ammo'), ('鋼材', 'steel'), ('ボーキサイト', 'bauxite')]}
        items = []
        for label, (item_type, korean) in ITEMS.items():
            match = re.search(re.escape(label) + r'×(\d+)(?:[～~](\d+))?', reward_text)
            if match:
                items.append({'type': item_type, 'name': korean, 'min': int(match[1]),
                              'max': int(match[2] or match[1])})
        fleet_count = re.search(r'(?:最低|全)(\d+)隻', condition)
        if fleet_count is None:
            raise ValueError(f'Missing fleet count: {code}')
        stats = {STATS[label]: int(n) for label, n in re.findall(r'(火力|対空|対潜|索敵)\s*(\d+)', condition)}
        label = text(cells[1])
        details[code] = {
            'monthly': 'マンスリー' in label,
            'combat_type': 2 if '交戦II型' in label else 1 if '交戦I型' in label else 0,
            'minutes': h * 60 + m,
            'flagship_level': levels[0] if levels else None,
            'fleet_level': levels[1] if len(levels) > 1 else None,
            'fleet_count': int(fleet_count[1]),
            'stats': stats, 'resources': resources, 'items': items,
            'condition_jp': condition,
            'unlocks': unlocks[code],
        }

    summary = next(t for t in tables if all(label in text(t) for label in ('燃料理論値', '改修', '家具箱'))
                   and len(t.find_all('tr')) > 50)
    formations = {}
    for row in summary.find_all('tr'):
        cells = row.find_all(['th', 'td'], recursive=False)
        if cells and CODE.fullmatch(text(cells[0])):
            code = normalize_code(text(cells[0]))
            formations[code] = text(cells[5])
            data = details[code]
            assert tuple(map(int, text(cells[2]).split(':'))) == divmod(data['minutes'], 60), code
            assert int(re.search(r'\d+', text(cells[4]))[0]) == data['fleet_count'], code
            for idx, key in enumerate(('fuel', 'ammo', 'steel', 'bauxite'), 9):
                assert int(text(cells[idx]) or 0) == data['resources'][key], (code, key)
    assert set(details) == set(unlocks), (set(details) - set(unlocks), set(unlocks) - set(details))
    assert len(details) == 63 and len(formations) == 61
    return details, formations


def parse_eo(root):
    calculator_file = root / 'ElectronicObserver.Avalonia/ExpeditionCalculator/ExpeditionCalculatorData.cs'
    conditions_file = root / 'ElectronicObserver/Data/MissionClearCondition.cs'
    calculator = calculator_file.read_text(encoding='utf-8-sig')
    entries = {}
    for block in re.split(r'(?=\bId = \d+,)', calculator)[1:]:
        game_id = int(re.search(r'Id = (\d+)', block)[1])
        code = normalize_code(re.search(r'DisplayId = "([A-Z\d]+)"', block)[1])
        duration = re.search(r'Duration = new\((\d+), (\d+), (\d+)\)', block)
        entries[code] = {
            'game_id': game_id,
            'minutes': int(duration[1]) * 60 + int(duration[2]),
            'monthly': 'IsMonthly = true' in block,
            'great_success_type': re.search(r'GreatSuccessType = GreatSuccessType\.(\w+)', block)[1],
            'resources': {key: int(m[1]) if (m := re.search(label + r' = (\d+)', block)) else 0
                          for label, key in [('Fuel', 'fuel'), ('Ammo', 'ammo'), ('Steel', 'steel'), ('Bauxite', 'bauxite')]},
            'items': {kind: int(count) for kind, count in re.findall(r'Type = UseItemId\.(\w+),\s*Amount = (\d+)', block)},
        }
    code_text = conditions_file.read_text(encoding='utf-8-sig').split('_ => DefaultCase')[0]
    checks = {}
    for match in re.finditer(r'(\d+) => result(.*?)(?=\n\s*//|\n\s*\d+ =>|\Z)', code_text, re.S):
        checks[int(match[1])] = match[2]
    return entries, checks, [calculator_file, conditions_file]


ESCORT = ['경순1 (구축+해방)2', '호위항모1 (구축2 또는 해방2)', '구축1 해방3', '연순1 해방2']
FORMATIONS = {
    '4': ESCORT, '5': ESCORT, '9': ESCORT, '42': ESCORT,
    'A3': ['경순1 (구축+해방)3', '경순1 해방2', *ESCORT[1:]],
    'A4': ESCORT,
    'A5': ['경순1 구축3', '경순1 해방2', *ESCORT[1:]],
    'A6': ['경순1 구축3', '경순1 해방2', *ESCORT[1:]],
    '43': ['호위항모1(기함) (구축2 또는 해방2)',
           '경항모1(기함) 경순1 (구축+해방)4', '경항모1(기함) 경순1 해방2',
           '경항모1(기함) 구축1 해방3', '경항모1(기함) 연순1 해방2',
           '경항모1(기함) 호위항모1 (구축2 또는 해방2)'],
    '44': ['(수모2 또는 수모1 항모1) 경순1 (구축+해방)2'],
}
FLAGSHIPS = {'24': '경순1', '32': '연순1', '40': '경순1', '43': '경항모1', '45': '경항모1',
             'B6': '경순1', 'D1': '수모1', 'D2': '잠수모함1', 'D3': '잠수모함1', 'E1': '중순1'}
DRUMS = {'21': (3, 3), '37': (4, 3), '38': (8, 4), '44': (6, 3), 'E2': (4, 3)}


def formation(raw):
    if not raw:
        return '함종 자유'
    for jp, ko in [('潜母艦', '잠수모함'), ('(駆+海防)', '(구축+해방)'), ('航戦', '항전'),
                   ('水母', '수모'), ('軽母', '경항모'), ('練巡', '연순'), ('護母', '호위항모'),
                   ('空母', '항모계(수모 포함)'), ('海防', '해방'), ('潜', '잠수함'),
                   ('軽', '경순'), ('重', '중순'), ('駆', '구축')]:
        raw = raw.replace(jp, ko)
    if re.search(r'[一-龯ぁ-んァ-ヶ]', raw):
        raise ValueError(f'Untranslated formation: {raw}')
    return raw


def build(har_file, eo_root, data_root):
    har = json.loads(har_file.read_text(encoding='utf-8'))
    entry = next(e for e in har['log']['entries'] if e['request']['url'] == WIKI)
    html = entry['response']['content']['text']
    wiki, formations = parse_wiki(html)
    eo, checks, files = parse_eo(eo_root)
    translation_file = data_root / 'Translations/ko-KR/expedition.json'
    translations = json.loads(translation_file.read_text(encoding='utf-8-sig'))
    report = {'source': WIKI, 'wiki_html_sha256': hashlib.sha256(html.encode()).hexdigest(),
              'har_captured_at': entry['startedDateTime'],
              'eo_sources': [source(f, eo_root) for f in files],
              'translation_source': source(translation_file, data_root),
              'checked': {}, 'differences': []}
    expeditions = {}
    for code, raw in wiki.items():
        game_id = eo[code]['game_id'] if code in eo else int(code)
        title = translations[str(game_id)]['name']
        if not re.search(r'[가-힣]', title):
            raise ValueError(f'Missing Korean name: {code}')
        data = {key: value for key, value in raw.items() if key != 'condition_jp'}
        drum_match = re.search(r'(\d+)隻以上に\s*ドラム缶.*?合計(\d+)個以上必要', raw['condition_jp'])
        drums = {'count': int(drum_match[2]), 'ships': int(drum_match[1])} if drum_match else None
        assert drums == (dict(zip(('count', 'ships'), DRUMS[code])) if code in DRUMS else None), code
        data.update({'game_id': game_id, 'name': re.sub(r'\s+', '', title),
                     'support': code in ('33', '34'),
                     'drum_type': eo.get(code, {}).get('great_success_type') == 'Drum',
                     'fleet_options': FORMATIONS.get(code, [formation(formations.get(code, '駆2'))]),
                     'drums': drums})
        if code in FLAGSHIPS and code not in FORMATIONS:
            data['fleet_options'] = [option.replace(FLAGSHIPS[code], FLAGSHIPS[code] + '(기함)')
                                     for option in data['fleet_options']]
        if code == '44':
            data['condition_note'] = '항모는 수모와 별개인 항모계 1척'
        checked = []
        if code in eo:
            for field in ('minutes', 'monthly', 'resources'):
                checked.append(field)
                if data[field] != eo[code][field]:
                    report['differences'].append({'code': code, 'field': field, 'wiki': copy.deepcopy(data[field]), 'eo': eo[code][field]})
            wiki_items = {item['type']: item['max'] for item in data['items']}
            checked.append('item_maximums')
            if wiki_items != eo[code]['items']:
                report['differences'].append({'code': code, 'field': 'item_maximums', 'wiki': wiki_items, 'eo': eo[code]['items']})
        calls = checks[game_id]
        if code not in FORMATIONS:
            type_labels = {'LightCruiser': '軽', 'Destroyer': '駆', 'HeavyCruiser': '重',
                           'AviationBattleship': '航戦', 'SeaplaneTender': '水母',
                           'SubmarineTender': '潜母艦'}
            for ship_type, count in re.findall(r'CheckShipCountByType\(ShipTypes\.(\w+), (\d+)\)', calls):
                assert type_labels[ship_type] + count in formations.get(code, '駆2'), (code, ship_type)
            for method, label in [('CheckSmallShipCount', '(駆+海防)'), ('CheckSubmarineCount', '潜'),
                                  ('CheckAircraftCarrierCount', '空母')]:
                match = re.search(method + r'\((\d+)', calls)
                if match:
                    assert label + match[1] in formations[code], (code, method)
            checked.append('fleet_type_counts')
        if code in FLAGSHIPS:
            expected = {'경순1': 'LightCruiser', '연순1': 'TrainingCruiser', '수모1': 'SeaplaneTender',
                        '잠수모함1': 'SubmarineTender', '중순1': 'HeavyCruiser', '경항모1': 'LightAircraftCarrier'}
            assert 'CheckFlagshipType(ShipTypes.' + expected[FLAGSHIPS[code]] + ')' in calls, code
            checked.append('flagship_type')
        if drums:
            equipped = re.search(r'CheckEquippedShipCount\(EquipmentTypes.TransportContainer, (\d+)\)', calls)
            equipment = re.search(r'CheckEquipmentCount\(EquipmentTypes.TransportContainer, (\d+)\)', calls)
            assert equipped and int(equipped[1]) == drums['ships'], code
            assert (int(equipment[1]) if equipment else int(equipped[1])) == drums['count'], code
            checked.append('required_drums')
        for method, field in [('CheckFlagshipLevel', 'flagship_level'), ('CheckLevelSum', 'fleet_level'),
                              ('CheckShipCount', 'fleet_count')]:
            match = re.search(r'\.' + method + r'\((\d+)\)', calls)
            if match:
                checked.append(field)
                if int(match[1]) != data[field]:
                    report['differences'].append({'code': code, 'field': field, 'wiki': data[field], 'eo': int(match[1])})
        eo_stats = {field: int(m[1]) for method, field in [('CheckFirepower', 'firepower'), ('CheckAA', 'aa'),
                                                         ('CheckASW', 'asw'), ('CheckLOS', 'los')]
                    if (m := re.search(r'\.' + method + r'\((\d+)\)', calls))}
        checked.append('stats')
        if eo_stats != data['stats']:
            report['differences'].append({'code': code, 'field': 'stats', 'wiki': data['stats'], 'eo': eo_stats})
        report['checked'][code] = checked
        expeditions[code] = data
    report['count'] = len(expeditions)
    report['resolution'] = 'Initial wiki/EO comparison; review cross-source corrections before publication.'
    catalog = {'schema': 1, 'source': WIKI, 'wiki_html_sha256': report['wiki_html_sha256'],
               'captured_at': report['har_captured_at'], 'expeditions': expeditions}
    corrections_file = Path(__file__).resolve().parents[1] / 'data/expedition_corrections.json'
    if corrections_file.exists():
        corrections = json.loads(corrections_file.read_text(encoding='utf-8'))
        for change in corrections['changes']:
            target = catalog['expeditions'][change['code']]
            for part in change['path'][:-1]:
                target = target[part]
            if target[change['path'][-1]] not in (change['before'], change['after']):
                raise ValueError(f'Source changed; review correction: {change["code"]}/{change["path"]}')
            target[change['path'][-1]] = copy.deepcopy(change['after'])
        catalog['crosscheck'] = corrections['crosscheck_report']
        report['crosscheck'] = corrections['crosscheck_report']
        report['resolution'] = ('Original EO/wiki differences are retained below. Final values apply '
                                'reviewed game-master and cross-source corrections; see crosscheck report.')
        for difference in report['differences']:
            selected = catalog['expeditions'][difference['code']]
            difference['selected'] = ({item['type']: item['max'] for item in selected['items']}
                                      if difference['field'] == 'item_maximums' else selected[difference['field']])
    return {'catalog': catalog, 'verification': report}


if __name__ == '__main__':
    print(json.dumps(build(*(Path(arg) for arg in sys.argv[1:4])), ensure_ascii=False))
