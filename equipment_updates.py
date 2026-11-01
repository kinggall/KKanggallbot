"""Validated public-master supplements; existing encyclopedia CSV wins."""
import csv
import json

FIELDS = {
    '火力': 'api_houg', '雷装': 'api_raig', '対空': 'api_tyku',
    '装甲': 'api_souk', '対潜': 'api_tais', '回避': 'api_houk',
    '索敵': 'api_saku', '命中': 'api_houm', '爆装': 'api_baku',
    '運': 'api_luck', '射程': 'api_leng',
}


def integer(value):
    if type(value) is not int or not -1000 <= value <= 10000:
        raise ValueError('Invalid public equipment number')
    return value


def master_items(document):
    if isinstance(document, dict):
        document = document.get('api_data', document)
        document = document['api_mst_slotitem']
    if not isinstance(document, list) or len(document) < 500:
        raise ValueError('Incomplete public equipment master')
    result = {}
    for item in document:
        item_id = integer(item['api_id'])
        if not 0 < item_id < 1500:
            continue
        if item_id in result:
            raise ValueError('Duplicate public equipment ID')
        name = item['api_name']
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError('Invalid public equipment name')
        types = item['api_type']
        if not isinstance(types, list) or len(types) != 5:
            raise ValueError('Invalid public equipment type')
        values = {column: integer(item[field]) for column, field in FIELDS.items()}
        values.update({'装備ID': item_id, '装備種3': integer(types[2]),
                       '配置コスト': integer(item.get('api_cost', 0)),
                       '戦闘行動半径': integer(item.get('api_distance', 0))})
        result[item_id] = dict(name_jp=name, values=values)
    if len(result) < 500:
        raise ValueError('Incomplete normal equipment master')
    return result


def csv_ids(root):
    with (root / 'equipments.csv').open(encoding='cp932', newline='') as stream:
        return {int(row['装備ID']) for row in csv.DictReader(stream)}


def supplement_rows(root):
    path = root / 'data/equipment_updates.json'
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('schema') != 1:
        raise ValueError('Invalid equipment supplement schema')
    result, seen = [], set()
    existing = csv_ids(root)
    for item in document['items']:
        values = item['values']
        item_id = integer(values['装備ID'])
        if not 0 < item_id < 1500 or item_id in seen:
            raise ValueError('Invalid supplemental equipment ID')
        seen.add(item_id)
        for field in [*FIELDS, '装備種3', '配置コスト', '戦闘行動半径']:
            integer(values[field])
        if not isinstance(item['name_jp'], str) or not item['name_jp'].strip():
            raise ValueError('Missing supplemental equipment name')
        if item_id not in existing:
            result.append(item)
    return result
