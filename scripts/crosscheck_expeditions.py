"""Cross-check expedition facts without assuming one wiki is always correct.

Print {catalog, crosscheck, corrections} JSON. Arguments:
NAMU_HAR KC3_CHECKOUT GAME_DATA_CHECKOUT EO_CHECKOUT BOT_ROOT
Reuses the original wiki/EO comparison and needs beautifulsoup4 when rebuilding.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from bs4 import BeautifulSoup
from build_expeditions import parse_eo

RESOURCES = ('fuel', 'ammo', 'steel', 'bauxite')
ITEMS = {
    1: ('InstantRepair', '수복재'), 2: ('InstantConstruction', '건조재'),
    3: ('DevelopmentMaterial', '자재'), 4: ('ImproveMaterial', '나사'),
    10: ('FurnitureBoxSmall', '가구함(소)'), 11: ('FurnitureBoxMedium', '가구함(중)'),
    12: ('FurnitureBoxLarge', '가구함(대)'), 59: ('MoraleFoodIrako', '이라코'),
}
STATS = (('firepower', '화력'), ('aa', '대공'), ('asw', '대잠'), ('los', '색적'))


def git_file(root, path):
    raw = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:' + path])
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    return raw, {'file': path, 'commit': commit, 'sha256': hashlib.sha256(raw).hexdigest()}


def normal(code):
    return str(int(code)) if code.isdigit() else code


def parse_namu(path):
    har = json.loads(path.read_text(encoding='utf-8'))
    entry = next(e for e in har['log']['entries'] if e['request']['url'].startswith('https://namu.wiki/w/')
                 and e['response']['content'].get('mimeType') == 'text/html')
    html = entry['response']['content']['text']
    soup = BeautifulSoup(html, 'html.parser')
    details = {}
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if not any([c.get_text(' ', strip=True) for c in r.find_all(['td', 'th'], recursive=False)] ==
                   ['번호', '원정명', '난이도', '내용', '원정시간', '소비연료', '소비탄약'] for r in rows):
            continue
        for i, row in enumerate(rows):
            cells = row.find_all(['td', 'th'], recursive=False)
            if len(cells) != 7 or not re.fullmatch(r'\d{1,2}|[ABDE]\d', cells[0].get_text(strip=True)):
                continue
            code = normal(cells[0].get_text(strip=True))
            reward = rows[i + 1].get_text(' ', strip=True)
            level_cells = rows[i + 2].find_all(['td', 'th'], recursive=False)
            level_text = level_cells[0].get_text(' ', strip=True)
            condition = level_cells[1].get_text(' ', strip=True)
            duration = cells[4].get_text(' ', strip=True)
            hours = re.search(r'(\d+)시간', duration)
            minutes = re.search(r'(\d+)분', duration)
            if re.fullmatch(r'\d+:\d+:\d+', duration):
                h, m, sec = map(int, duration.split(':'))
                total = h * 60 + m
            else:
                total = int(hours[1]) * 60 if hours else 0
                total += int(minutes[1]) if minutes else 0
            resource_values = {}
            for label, key in [('연료', 'fuel'), ('탄약', 'ammo'), ('강재', 'steel'),
                               ('보크사이트|보크|보키', 'bauxite')]:
                match = re.search(r'(?:' + label + r')\s*(\d+)', reward)
                if match:
                    resource_values[key] = int(match[1])
            match_flag = re.search(r'Lv\s*(\d+)', level_text)
            match_total = re.search(r'(?:합계\s*Lv|레벨\s*총합|총레벨|레벨\s*총합)\s*(\d+)', level_text + ' ' + condition)
            stats = {key: int(m[1]) for key, label in STATS
                     if (m := re.search(label + r'\s*(\d+)', condition))}
            drum_ships = re.search(r'드럼통\s*(?:장착함|장비함)\s*(\d+)\s*척', condition)
            drum_count = re.search(r'드럼통\s*(?:총합|합계|총)?\s*(\d+)\s*(?:개|기)', condition)
            details[code] = {'minutes': total, 'resources_listed': resource_values,
                             'flagship_level': int(match_flag[1]) if match_flag else None,
                             'fleet_level': int(match_total[1]) if match_total else None,
                             'stats_listed': stats,
                             'drums_listed': {'ships': int(drum_ships[1]), 'count': int(drum_count[1])}
                             if drum_ships and drum_count else None}
    summary = next(t for t in tables if '최소 요구 능력치' in t.get_text(' ', strip=True))
    monthly = {}
    for row in summary.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in row.find_all(['td', 'th'], recursive=False)]
        if len(cells) == 15 and re.fullmatch(r'\d{1,2}|[ABDE]\d', cells[0]):
            monthly[cells[0]] = {'flagship_level': int(cells[4]), 'fleet_level': int(cells[5]),
                                 'fleet_count': int(cells[6]),
                                 'stats': {key: int(value) for (key, _), value in zip(STATS, cells[8:12])
                                           if value.isdigit()},
                                 'drums': {'ships': int(cells[12]), 'count': int(cells[13])}
                                 if cells[12].isdigit() and cells[13].isdigit() else None}
    if len(details) != 63 or len(monthly) != 16:
        raise ValueError(f'Namu table structure changed: {len(details)}, {len(monthly)}')
    source = {'url': entry['request']['url'], 'captured_at': entry['startedDateTime'],
              'html_sha256': hashlib.sha256(html.encode()).hexdigest()}
    return details, monthly, source


def reconcile(namu_har, kc3_root, master_root, eo_root, root):
    catalog = json.loads((root / 'data/expeditions.json').read_text(encoding='utf-8'))
    policy_path = root / 'data/expedition_corrections.json'
    old_policy = json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.exists() else {'changes': []}
    # Reconstruct the wiki baseline so that running this again is reproducible.
    for change in old_policy['changes']:
        target = catalog['expeditions'][change['code']]
        for part in change['path'][:-1]:
            target = target[part]
        target[change['path'][-1]] = change['before']
    details, monthly, namu_source = parse_namu(namu_har)
    raw_kc3, kc3_source = git_file(kc3_root, 'src/library/helpers/KanColleHelpers.js')
    javascript = raw_kc3.decode('utf-8-sig')
    income = javascript.split('var getExpeditionIncomeBase = function (eId) {', 1)[1].split('exports["getExpeditionIncomeBase"]', 1)[0]
    kc3_resources = {int(i): dict(zip(RESOURCES, map(int, (a, b, c, d)))) for i, a, b, c, d in re.findall(
        r'if \(eId === (\d+)\) \{\s*return income\((\d+)\)\((\d+)\)\((\d+)\)\((\d+)\)', income)}
    kc3_resources.update({33: dict.fromkeys(RESOURCES, 0), 34: dict.fromkeys(RESOURCES, 0)})
    requirements = javascript.split('var getExpeditionRequirement = function (v) {', 1)[1].split('var fromRawShip', 1)[0]
    kc3_requirements = {}
    for game_id, block in re.findall(r'if \(v === (\d+)\) \{(.*?)\n      \}', requirements, re.S):
        fsl = re.search(r'fslAndSc\((\d+)\)\((\d+)\)', block)
        levels = re.search(r'lvlCnt\((\d+)\)', block)
        drum_ships = re.search(r'new FleetShipWithDrum\((\d+)\)', block)
        drum_count = re.search(r'new FleetDrum\((\d+)\)', block)
        kc3_requirements[int(game_id)] = {
            'flagship_level': int(fsl[1]) if fsl else None, 'fleet_count': int(fsl[2]) if fsl else None,
            'fleet_level': int(levels[1]) if levels else None,
            'stats': {key: int(m[1]) for method, key in [('fpTotal', 'firepower'), ('aaTotal', 'aa'),
                                                       ('aswTotal', 'asw'), ('losTotal', 'los')]
                      if (m := re.search(method + r'\((\d+)\)', block))},
            'drums': {'ships': int(drum_ships[1]), 'count': int(drum_count[1])}
            if drum_ships and drum_count else None,
        }
    raw_master, master_source = git_file(master_root, 'api/api_start2.json')
    masters = {normal(item['api_disp_no']): item for item in json.loads(raw_master)['api_mst_mission']}
    eo, eo_checks, _ = parse_eo(eo_root)
    if set(details) != set(catalog['expeditions']) or set(masters) != set(details):
        raise ValueError('Cross-source expedition ID mismatch')
    changes = []
    records = {}
    source_disagreements = []
    def change(code, path, value, reason, evidence):
        target = catalog['expeditions'][code]
        for part in path[:-1]:
            target = target[part]
        before = copy.deepcopy(target[path[-1]])
        if before != value:
            changes.append({'code': code, 'path': path, 'before': before, 'after': value,
                            'reason': reason, 'evidence': evidence})
            target[path[-1]] = copy.deepcopy(value)
    for code, data in catalog['expeditions'].items():
        wiki_baseline = copy.deepcopy(data)
        game_id = data['game_id']
        master = masters[code]
        if game_id not in kc3_resources or game_id not in kc3_requirements:
            raise ValueError(f'KC3 record missing: {code}')
        master_items = {}
        for field in ('api_win_item1', 'api_win_item2'):
            item_id, count = master[field]
            if item_id:
                kind, label = ITEMS[item_id]
                master_items[kind] = {'type': kind, 'name': label, 'min': 0, 'max': count}
        selected_items = [master_items[kind] for kind, _ in ITEMS.values() if kind in master_items]
        change(code, ['items'], selected_items,
               'Use archived game master item kind/maximum instead of wiki/EO item labels.', ['game_master'])
        for field, key in [('minutes', 'api_time'), ('monthly', 'api_reset_type'), ('combat_type', 'api_damage_type')]:
            expected = bool(master[key]) if field == 'monthly' else master[key]
            change(code, [field], expected, 'Use archived game master metadata.', ['game_master'])
        for index, key in enumerate(RESOURCES):
            current = data['resources'][key]
            candidate = kc3_resources[game_id][key]
            if current != candidate:
                if eo[code]['resources'][key] != candidate:
                    raise ValueError(f'Resource conflict needs manual review: {code}/{key}')
                evidence = ['KC3', 'EO']
                if details[code]['resources_listed'].get(key) == candidate:
                    evidence.append('namu_detail')
                if bool(current) != bool(master['api_win_mat_level'][index]):
                    if bool(candidate) != bool(master['api_win_mat_level'][index]):
                        raise ValueError(f'Game master contradicts resource presence: {code}/{key}')
                    evidence.append('game_master_resource_presence')
                if code == '10' and key == 'bauxite':
                    evidence.append('user_kamigame_screenshot')
                change(code, ['resources', key], candidate,
                       'Use matching EO/KC3 calculator values; retain source conflicts in report.', evidence)
        for index, key in enumerate(RESOURCES):
            assert bool(data['resources'][key]) == bool(master['api_win_mat_level'][index]), (code, key)
        calls = eo_checks[game_id]
        eo_stats = {key: int(m[1]) for method, key in [('CheckFirepower', 'firepower'), ('CheckAA', 'aa'),
                                                      ('CheckASW', 'asw'), ('CheckLOS', 'los')]
                    if (m := re.search(method + r'\((\d+)\)', calls))}
        eo_conditions = {'stats': eo_stats}
        for field, method in [('flagship_level', 'CheckFlagshipLevel'), ('fleet_level', 'CheckLevelSum')]:
            match = re.search(method + r'\((\d+)\)', calls)
            eo_conditions[field] = int(match[1]) if match else None
        records[code] = {
            'namu_detail': details[code], 'namu_monthly_summary': monthly.get(code),
            'KC3': {'resources': kc3_resources[game_id], **kc3_requirements[game_id]},
            'EO_resources': eo.get(code, {}).get('resources'),
            'EO_conditions': eo_conditions,
            'game_master': {'item_maximums': {k: v['max'] for k, v in master_items.items()},
                            'resource_levels': master['api_win_mat_level'], 'minutes': master['api_time'],
                            'monthly': bool(master['api_reset_type']), 'combat_type': master['api_damage_type']},
        }
        for field in ('flagship_level', 'fleet_level'):
            values = {'wiki': wiki_baseline[field], 'EO': eo_conditions[field],
                      'KC3': kc3_requirements[game_id][field], 'namu_detail': details[code][field]}
            if code in monthly:
                values['namu_monthly_summary'] = monthly[code][field]
            listed = [v for v in values.values() if v is not None]
            if listed and len(set(listed)) > 1:
                source_disagreements.append({'code': code, 'field': field, 'selected': data[field], 'values': values})
        for key, _ in STATS:
            values = {'wiki': wiki_baseline['stats'].get(key), 'EO': eo_stats.get(key),
                      'KC3': kc3_requirements[game_id]['stats'].get(key),
                      'namu_detail': details[code]['stats_listed'].get(key)}
            if code in monthly:
                values['namu_monthly_summary'] = monthly[code]['stats'].get(key)
            listed = [v for v in values.values() if v is not None]
            if len(set(listed)) > 1 or (listed and any(v is None for v in values.values())):
                source_disagreements.append({'code': code, 'field': 'stats.' + key,
                                             'selected': data['stats'].get(key), 'values': values})
    # This actual result supports 14 even though Namu/EO list the older 240.
    assert catalog['expeditions']['14']['resources']['ammo'] == 280
    assert 280 * 1.5 * 1.2 == 504
    internal_conflicts = []
    for code, summary in monthly.items():
        detailed = details[code]
        for field in ('flagship_level', 'fleet_level'):
            if detailed[field] is not None and detailed[field] != summary[field]:
                internal_conflicts.append({'code': code, 'field': field, 'detail': detailed[field], 'summary': summary[field]})
        for key, value in detailed['stats_listed'].items():
            if key in summary['stats'] and value != summary['stats'][key]:
                internal_conflicts.append({'code': code, 'field': key, 'detail': value, 'summary': summary['stats'][key]})
        if detailed['drums_listed'] and summary['drums'] and detailed['drums_listed'] != summary['drums']:
            internal_conflicts.append({'code': code, 'field': 'drums',
                                       'detail': detailed['drums_listed'], 'summary': summary['drums']})
    report = {
        'sources': {'namu': namu_source, 'KC3': kc3_source, 'game_master': master_source},
        'method': 'No fixed preference for a wiki. Archive master determines item types/maxima and metadata; '
                  'exact resource amounts use corroborating calculators, screenshots and wiki tables. '
                  'api_win_mat_level is only a presence/level indicator, never an exact amount.',
        'count': len(records), 'records': records, 'namu_internal_conflicts': internal_conflicts,
        'condition_source_disagreements': source_disagreements,
        'game_screenshot_14': {'context': 'User states expedition 14, great success, four regular Daihatsu',
                               'observed_ammo': 504, 'great_success': 1.5, 'equipment_bonus': 1.2, 'base_ammo': 280},
        'kamigame_10': {'url': 'https://kamigame.jp/艦これ/page/150509543137272993.html',
                        'evidence': 'User-provided screenshot; direct request was blocked by environment proxy',
                        'resources': {'fuel': 0, 'ammo': 50, 'steel': 0, 'bauxite': 30}},
        'unresolved': [
            {'code': 'A3', 'field': 'aa', 'wiki': 'not listed', 'KC3': 'not listed', 'EO': 59,
             'namu_detail': 162, 'decision': 'Keep published ASW280/LOS60; no claim that an AA minimum is disproven.'},
            {'code': 'D2', 'field': 'los', 'wiki': 70, 'namu_monthly_summary': 70, 'EO': 'not listed',
             'KC3': 'not listed', 'decision': 'Keep LOS70 as a conservative published requirement; actual minimum not proven.'},
        ],
        'changes': changes,
    }
    corrections = {'crosscheck_report': 'data/expedition_crosscheck.json', 'changes': changes}
    catalog['crosscheck'] = corrections['crosscheck_report']
    return {'catalog': catalog, 'crosscheck': report, 'corrections': corrections}


if __name__ == '__main__':
    print(json.dumps(reconcile(*(Path(arg) for arg in sys.argv[1:6])), ensure_ascii=False))
