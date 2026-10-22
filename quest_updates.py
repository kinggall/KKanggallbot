"""Reviewed wiki snapshots layered over the upstream quest database."""
from copy import deepcopy
import json
import unicodedata


# The archived wiki snapshot used sequential numbers for all sortie tasks.
# EO separates onetime, weekly and monthly codes. Never retain conflicting
# sequential numbers as command aliases.
OCTOBER_CODES = {
    '2610 B1': ('2610 B1', 984),
    '2610 B2': ('2610 Bw1', 985),
    '2610 B3': ('2610 B2', 986),
    '2610 B4': ('2610 Bm1', 987),
    '2610 B5': ('2610 B3', 1038),
    '2610 B6': ('2610 Bw2', 1039),
    '2610 B7': ('2610 Bm2', 1040),
    '2610 B8': ('2610 B4', 1002),
    '2610 C1': ('2610 Cw1', 359),
    '2610 F1': ('2610 Fm1', 1119),
    '2610 F2': ('2610 F1', 1171),
}


def canonicalize_october(update):
    """Convert the reviewed snapshot once, preserving original source rows."""
    update = deepcopy(update)
    update['source']['code_policy'] = 'EO canonical codes; original wiki codes retained only as source_wiki_id, not search aliases'
    update['source']['code_reference'] = 'ElectronicObserverEN/Data@79a2c818924060dcb3b18dbdb043b855bcc04694:Data/Quests.json'
    for row in update['quests']:
        source = row.get('source_wiki_id', row['wiki_id'])
        if source not in OCTOBER_CODES:
            continue
        already = 'source_wiki_id' in row
        code, api_id = OCTOBER_CODES[source]
        row.update(wiki_id=code, source_wiki_id=source, game_api_id=api_id)
        row['aliases'] = [code.replace(' ', '')]
        if not already:
            row['prerequisite_codes'] = [OCTOBER_CODES.get(c, (c, None))[0]
                                         for c in row['prerequisite_codes']]
    return update


def identity(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def apply_updates(data, root):
    path = root / 'data/quest_wiki_updates.json'
    if not path.exists():
        return data
    data = deepcopy(data)
    update = json.loads(path.read_text(encoding='utf-8'))
    by_code = {q['wiki_id'].replace(' ', '').casefold(): key for key, q in data['quests'].items()}
    keys = {}
    for row in update['quests']:
        code = row['wiki_id']
        if code in keys:
            raise ValueError('Duplicate wiki update: ' + code)
        key = str(row['game_api_id']) if row.get('game_api_id') else by_code.get(
            code.replace(' ', '').casefold(), 'wiki:' + code.replace(' ', ''))
        previous = data['quests'].get(key)
        if previous and previous.get('name_jp') and identity(previous['name_jp']) != identity(row['name_jp']):
            raise ValueError('Quest code/title conflict requires review: ' + code)
        keys[code] = key
        item = deepcopy(row)
        item['game_id'] = int(key) if key.isdigit() else key
        item['aliases'] = list(dict.fromkeys([*item.get('aliases', []), code.replace(' ', '')]))
        data['quests'][key] = item
        data['codes'][key] = code
    lookup = {q['wiki_id'].replace(' ', '').casefold(): key for key, q in data['quests'].items()}
    lookup.update({code.replace(' ', '').casefold(): key for key, code in data['codes'].items()
                   if code.replace(' ', '').casefold() not in lookup})
    for row in update['quests']:
        item = data['quests'][keys[row['wiki_id']]]
        item['prereqs'] = []
        for code in item.pop('prerequisite_codes'):
            key = lookup.get(code.replace(' ', '').casefold())
            if key is None:
                raise ValueError('Unresolved wiki prerequisite: ' + code)
            item['prereqs'].append(int(key) if key.isdigit() else key)
    data['sources']['wiki_new_quests'] = update['source']
    return data
