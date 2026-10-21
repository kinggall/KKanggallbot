"""Offline quest identity/duplicate audit and conservative guide comparisons."""
import argparse
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import quests
from scripts.collect_zekamashi import Document, Node, normalized, select_article, visible_text, visible_walk


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def rules(value, field):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == field:
                found.extend(child if isinstance(child, list) else [child])
            else:
                found.extend(rules(child, field))
    elif isinstance(value, list):
        for child in value:
            found.extend(rules(child, field))
    return found


def duplicate_groups(items):
    groups = defaultdict(list)
    for key, row in items.items():
        if not row.get('unavailable'):
            groups[digest(row['requirements'])].append({'id': key, 'code': row['wiki_id']})
    return [rows for rows in groups.values() if len(rows) > 1]


def battle_results(sorties):
    return {r.get('result') for r in sorties if not (
        r.get('result') is None and not r.get('boss')
        and (r.get('node') or quests.values(r.get('map', [])) == ['1-6']))}


def composition_warnings(items):
    warnings = []
    for row in items.values():
        for comp in find_compositions(row['requirements']):
            minimum = sum(c.get('amount', 1)[0] if isinstance(c.get('amount'), list)
                          else c.get('amount', 1) for c in comp)
            if minimum > 6:
                warnings.append({'code': row['wiki_id'], 'minimum': minimum, 'comp': comp,
                                 'note': 'Review fleet size or alternative-group meaning; do not automatically change it'})
    return warnings


def find_compositions(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'comp':
                yield child
            else:
                yield from find_compositions(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_compositions(child)


def source_audit(source):
    selected, raw, mismatches, mirrors = {}, [], [], []
    base = json.loads((source / 'quests.json').read_text(encoding='utf-8'))
    for folder in ('unverified', None, 'verified'):
        rows = [(str(p.relative_to(source)), json.loads(p.read_text(encoding='utf-8')))
                for p in sorted((source / folder).glob('quest_*.json'))] if folder else [('quests.json', r) for r in base.values()]
        for path, row in rows:
            key = str(row['game_id'])
            raw.append((path, row))
            selected[key] = row
            if path != 'quests.json' and Path(path).stem.removeprefix('quest_') != key:
                mismatches.append({'file': path, 'internal_id': key})
            if path.startswith('verified/') and key in base:
                changed = [f for f in ('wiki_id', 'requirements', 'rewards', 'prereqs')
                           if base[key].get(f) != row.get(f)]
                if changed:
                    mirrors.append({'file': path, 'changed_fields': changed})
    codes = defaultdict(list)
    for key, row in selected.items():
        codes[row['wiki_id'].casefold()].append(key)
    return {
        'revision': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
        'raw_records': len(raw), 'merged_records': len(selected),
        'layer_counts': dict(Counter(p.split('/')[0] for p, _ in raw)),
        'filename_id_mismatches': mismatches, 'verified_vs_base_changes': mirrors,
        'duplicate_external_codes': [{'code': c, 'ids': ids} for c, ids in codes.items() if len(ids) > 1],
        'identical_requirement_groups': duplicate_groups(selected),
    }


def guide_audit(article_zip, manifest_zip, catalog):
    names_by_id = {}
    with (ROOT / 'ships.csv').open(encoding='cp932', newline='') as stream:
        for row in csv.DictReader(stream):
            if int(row['艦船ID']) < 1500:
                names_by_id[int(row['艦船ID'])] = unicodedata.normalize('NFKC', row['艦名'])
    names = sorted(set(names_by_id.values()), key=lambda s: (-len(s), s))
    name_pattern = re.compile('|'.join(re.escape(n) for n in names if n))
    master_ships = json.loads((ROOT / 'data/development/start2.json').read_text(encoding='utf-8'))['api_mst_ship']
    classes = defaultdict(set)
    for ship in master_ships:
        if ship['api_id'] in names_by_id:
            classes[ship['api_ctype']].add(ship['api_id'])

    def family(name):
        ids = catalog.ship_queries.get(quests.normalized(name), set())
        return min(ids) if ids else name

    pages = {}
    with zipfile.ZipFile(article_zip) as archive:
        for filename in archive.namelist():
            if not filename.endswith('.html'):
                continue
            html = archive.read(filename).decode('utf-8-sig')
            doc = Document(html).root
            canonical = next((n.attrs.get('href', '').rstrip('/') for n in doc.walk()
                              if n.tag == 'link' and n.attrs.get('rel') == 'canonical'), None)
            if canonical:
                pages[canonical] = (filename, html)
    comparisons, identity_warnings = [], []
    with zipfile.ZipFile(manifest_zip) as archive:
        for filename in archive.namelist():
            if not filename.endswith('.json'):
                continue
            record = json.loads(archive.read(filename).decode('utf-8-sig'))
            page = pages.get(record.get('url', '').rstrip('/'))
            key = catalog.by_code.get(record['code'].casefold())
            if not page or key is None or record.get('status') != 'downloaded':
                continue
            quest = catalog.items[key]
            article_file, html = page
            h1 = next((n.text().strip() for n in Document(html).root.walk() if n.tag == 'h1'), '')
            title = quest['name_jp']
            if not normalized(h1).startswith(normalized(title)):
                identity_warnings.append({'code': quest['wiki_id'], 'url': record['url'], 'article_title': h1,
                                          'reason': 'Title only contains the quest name, not an exact leading title'})
                continue
            if quest['frequency'] == 'onetime' and 'マンスリー' in h1:
                identity_warnings.append({'code': quest['wiki_id'], 'url': record['url'], 'article_title': h1,
                                          'reason': 'Monthly guide matched a one-time quest with the same name'})
                continue
            active, condition = False, ''
            for node in visible_walk(select_article(html)):
                if node.tag == 'h2':
                    if active:
                        break
                    active = normalized(visible_text(node)) == normalized('任務情報')
                if active and node.tag == 'ul':
                    condition = unicodedata.normalize('NFKC', visible_text(node))
                    break
            if not condition:
                continue
            lines = [line.strip() for line in condition.splitlines() if line.strip()
                     and not line.strip().startswith('※') and not re.search('不要|対象外', line)]
            source_maps = set()
            for line in lines:
                source_maps.update(re.findall(r'(?<![A-Za-z0-9\u3400-\u9fff])([1-7]-[1-6](?:-[1-3])?)', line))
            actual_rules = rules(quest['requirements'], 'sortie')
            actual_maps = set()
            for rule in actual_rules:
                for area in quests.values(rule.get('map', [])):
                    actual_maps.add(quests.SORTIE_BOSS_MAPS.get(str(area), str(area)))
            issues = []
            fleet_lines = []
            for line in lines:
                if re.search(r'(?<![A-Za-z0-9\u3400-\u9fff])[1-7]-[1-6]', line):
                    break
                fleet_lines.append(line)
            fleet = ' '.join(fleet_lines).replace('水雷戦隊', '')
            named = {m.group() for m in name_pattern.finditer(fleet)
                     if fleet[m.end():m.end() + 1] not in {'型', '級', '系'} or '改' in m.group()}
            article_families = {family(n) for n in named}
            comp = rules(quest['requirements'], 'comp')
            saved_ids = set(rules(comp, 'ship_id'))
            for class_id in rules(comp, 'family_id'):
                saved_ids.update(classes[class_id])
            saved_ids.difference_update(rules(rules(quest['requirements'], 'comp_banned'), 'ship_id'))
            saved_names = {names_by_id[i] for i in saved_ids if i in names_by_id}
            saved_families = {family(n) for n in saved_names}
            if article_families and article_families != saved_families:
                issues.append({'field': 'named_ship_families', 'saved': sorted(saved_names), 'article': sorted(named),
                               'note': 'Potential missing/extra named ship; manually distinguish candidates, classes and alternatives'})
            if '旗艦' in fleet and not any(c.get('position') == 1 for c in comp):
                issues.append({'field': 'flagship', 'article': fleet,
                               'note': 'Article mentions a flagship but no fleet selector specifies position 1'})
            # A guide that only says 7-2 does not establish a gauge mismatch.
            generic = {m for m in source_maps if re.fullmatch(r'[1-7]-[1-6]', m)}
            comparable = {m[:3] if m[:3] in generic else re.sub(r'-P([1-3])$', r'-\1', m)
                          for m in actual_maps}
            if source_maps and comparable != source_maps:
                issues.append({'field': 'maps', 'saved': sorted(actual_maps), 'article': sorted(source_maps)})
            source_results = set(re.findall(r'([SAB])勝利', ' '.join(lines)))
            actual_results = battle_results(actual_rules)
            if len(source_results) == 1 and actual_rules and actual_results != source_results and actual_results <= {'S', 'A', 'B', None}:
                issues.append({'field': 'rank', 'saved': sorted(str(v) for v in actual_results), 'article': sorted(source_results)})
            source_times = {int(t) for t in re.findall(r'[SAB]勝利(?:以上)?\s*[×xX]\s*(\d+)回', ' '.join(lines))}
            actual_times = {r.get('times', 1) for r in actual_rules}
            if len(source_times) == 1 and actual_rules and actual_times != source_times:
                issues.append({'field': 'times', 'saved': sorted(actual_times), 'article': sorted(source_times)})
            comparisons.append({'code': quest['wiki_id'], 'url': record['url'], 'article_file': article_file,
                                'condition_jp': condition.strip(), 'candidates': issues})
    return {'compared': len(comparisons), 'identity_warnings': identity_warnings,
            'difference_candidates': [c for c in comparisons if c['candidates']],
            'scope': 'First condition list: explicit maps, common rank, explicit xN count, named ship families and presence of flagship selector only. Candidates require manual review; not all classes/counts/remodels are validated.'}


def wiki_audit(path, catalog):
    har = json.loads(path.read_text(encoding='utf-8-sig'))
    entry = next(e for e in har['log']['entries'] if unquote(e['request']['url']).split('?')[0]
                 == 'https://wikiwiki.jp/kancolle/任務/出撃任務')
    content = entry['response']['content']
    html = base64.b64decode(content['text']).decode('utf-8') if content.get('encoding') == 'base64' else content['text']
    compared, rank_candidates, rewards = 0, [], []
    for node in Document(html).root.walk():
        if node.tag != 'tr':
            continue
        cells = [c for c in node.children if isinstance(c, Node) and c.tag == 'td']
        if len(cells) < 9:
            continue
        code = visible_text(cells[0]).strip()
        key = catalog.by_code.get(code.casefold())
        if key is None or not re.fullmatch(r'B\d+', code):
            continue
        compared += 1
        row = catalog.items[key]
        text = unicodedata.normalize('NFKC', visible_text(cells[2]))
        ranks = set(re.findall(r'([SAB])勝利', text))
        saved = battle_results(rules(row['requirements'], 'sortie'))
        if len(ranks) == 1 and saved and saved <= {'S', 'A', 'B', None} and saved != ranks:
            rank_candidates.append({'code': code, 'saved': sorted(str(v) for v in saved),
                                    'wiki': sorted(ranks), 'condition_jp': text})
        resource_text = [visible_text(c).strip().replace(',', '') for c in cells[3:7]]
        if all(re.fullmatch(r'\d+', t) for t in resource_text):
            expected = list(map(int, resource_text))
            actual = row['rewards'].get('resources', [0, 0, 0, 0])
            if expected != actual:
                rewards.append({'code': code, 'saved': actual, 'wiki': expected})
    return {'compared_rows': compared, 'source_html_sha256': hashlib.sha256(html.encode()).hexdigest(),
            'rank_candidates': rank_candidates, 'resource_reward_candidates': rewards,
            'scope': 'Wiki table rank mentions and four fixed resource rewards only. Not a full fleet/reward-choice validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--articles', type=Path)
    parser.add_argument('--manifests', type=Path)
    parser.add_argument('--wiki-har', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/quest_source_audit.json')
    args = parser.parse_args()
    catalog = quests.QuestCatalog(ROOT)
    report = {'source': source_audit(args.source), 'bot': {'count': len(catalog.items),
              'identical_requirement_groups': duplicate_groups(catalog.items),
              'composition_size_candidates': composition_warnings(catalog.items)}}
    if args.articles and args.manifests:
        report['guides'] = guide_audit(args.articles, args.manifests, catalog)
    if args.wiki_har:
        report['wiki'] = wiki_audit(args.wiki_har, catalog)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: {f: v for f, v in section.items() if isinstance(v, (str, int))}
                      for k, section in report.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
