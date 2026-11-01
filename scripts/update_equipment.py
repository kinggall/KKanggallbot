"""Generate additions from public game masters, never rewrite the user CSV."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equipment_updates import master_items, csv_ids

MASTERS = [
    'https://raw.githubusercontent.com/Tibowl/api_start2/master/parsed/api_mst_slotitem.json',
    'https://raw.githubusercontent.com/kcwiki/kancolle-data/master/api/api_start2.json',
]
TRANSLATION = 'https://raw.githubusercontent.com/ElectronicObserverEN/Data/master/Translations/ko-KR/equipment.json'


def download(url):
    with urlopen(Request(url, headers={'User-Agent': 'KKanggallbot-equipment-update'}), timeout=30) as response:
        payload = response.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError('Public master too large')
    return json.loads(payload.decode('utf-8-sig')), hashlib.sha256(payload).hexdigest()


def build(root, fetch=download):
    all_items, sources = {}, []
    # Require both sources to succeed. A broken feed must not delete a good snapshot.
    for url in MASTERS:
        document, digest = fetch(url)
        items = master_items(document)
        for item_id, item in items.items():
            if item_id in all_items and all_items[item_id] != item:
                raise ValueError('Public masters disagree; manual review required: ' + str(item_id))
            all_items[item_id] = item
        sources.append({'url': url, 'sha256': digest})
    translations, digest = fetch(TRANSLATION)
    names = translations['equipment']
    if not isinstance(names, dict) or len(names) < 400:
        raise ValueError('Incomplete EO equipment translations')
    sources.append({'url': TRANSLATION, 'sha256': digest})
    baseline = csv_ids(root)
    additions = []
    for item_id, item in sorted(all_items.items()):
        if item_id in baseline:
            continue
        name = names.get(item['name_jp'], item['name_jp'])
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Invalid EO equipment translation')
        additions.append({**item, 'name': name})
    path = root / 'data/equipment_updates.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        old_ids = {r['values']['装備ID'] for r in old['items']} - baseline
        if old_ids - {r['values']['装備ID'] for r in additions}:
            raise ValueError('Published equipment disappeared; refusing update')
        old_names = {r['values']['装備ID']: r['name_jp'] for r in old['items']}
        if any(old_names.get(r['values']['装備ID'], r['name_jp']) != r['name_jp'] for r in additions):
            raise ValueError('Published equipment identity changed; manual review required')
    return {'schema': 1, 'sources': sources, 'items': additions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fetch and validate without writing')
    args = parser.parse_args()
    document = build(ROOT)
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    path = ROOT / 'data/equipment_updates.json'
    if not args.check and (not path.exists() or path.read_text(encoding='utf-8') != encoded):
        path.write_text(encoded, encoding='utf-8')
    print(f"Validated {len(document['items'])} additions; original CSV unchanged.")


if __name__ == '__main__':
    main()
