"""Reviewed wiki snapshots layered over the upstream quest database."""
from copy import deepcopy
import json
import unicodedata


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
        key = by_code.get(code.replace(' ', '').casefold(), 'wiki:' + code.replace(' ', ''))
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
