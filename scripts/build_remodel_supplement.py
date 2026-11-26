"""Audit active CSV remodel edges against a local kcwiki ship snapshot."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from equipment_lookup import EquipmentCatalog
from remodel_materials import normalize

FIELDS = ('blueprint', 'report', 'catapult', 'gunmat', 'airmat', 'armament',
          'development_material', 'construction_material', None, 'overseas', 'screw', 'arsenal')
EQUIPMENT = {'Skilled Lookouts':'熟練見張員', 'Type 21 Air Radar':'21号対空電探',
             'Type 22 Surface Radar':'22号対水上電探',
             'New Model High Temperature High Pressure Boiler':'新型高温高圧缶'}


def read(path, encoding='cp932'):
    with path.open(encoding=encoding, newline='') as file:
        return list(csv.DictReader(file))


def build(snapshot, revision, root=ROOT):
    payload = snapshot.read_bytes()
    wiki = json.loads(payload.decode('utf-8-sig'))
    by_id = {row['_api_id']:(key,row) for key,row in wiki.items() if type(row.get('_api_id')) is int}
    ships = {int(r['艦船ID']):r for r in read(root/'ships.csv') if 0<int(r['艦船ID'])<1500}
    raw = {int(r['艦船ID']):r for r in read(root/'data/observer_source/ships.csv')}
    equipment = {r['装備名']:int(r['装備ID']) for r in read(root/'equipments.csv')}
    names = EquipmentCatalog(root)
    def reference_id(ref):
        return wiki.get(ref.replace('/',' ').strip(),{}).get('_api_id') if isinstance(ref,str) else None
    routes = {}
    for sid,source in ships.items():
        if source['改装後'] in ('','-') or source['改装Lv'] in ('','0','-'):
            continue
        tid = int(raw[sid]['改装後'])
        target = ships[tid]
        source_record, source_wiki = by_id[sid]
        target_record, target_wiki = by_id[tid]
        if normalize(source['艦名']) != normalize(source_wiki['_japanese_name']) or source['改装後'] != target['艦名'] or normalize(target['艦名']) != normalize(target_wiki['_japanese_name']):
            raise ValueError(f'CSV/wiki ship identity mismatch: {sid}')
        if reference_id(target_wiki.get('_remodel_from')) == sid:
            cost, record, prefix = target_wiki, target_record, '_remodel_'
        elif reference_id(source_wiki.get('_remodel_to')) == tid and '_remodel_to_level' in source_wiki:
            cost, record, prefix = source_wiki, source_record, '_remodel_to_'
        else:
            raise ValueError(f'Unresolved directed remodel: {sid}')
        for suffix,field in (('level','改装Lv'),('ammo','改装弾薬'),('steel','改装鋼材')):
            if str(cost.get(prefix+suffix)) != source[field]:
                raise ValueError(f'CSV/wiki cost mismatch: {sid}/{field}')
        values = [cost.get(prefix+field,0) if field else 0 for field in FIELDS]
        if any(v is not None and (not isinstance(v,int) or v<0) for v in values):
            raise ValueError(f'Invalid remodel quantity: {sid}')
        counts = [None if value is None else int(value) for value in values]
        for index,field in ((0,'改装設計図'),(1,'戦闘詳報'),(2,'カタパルト'),(4,'新型航空兵装資材')):
            match = re.search(r'\d+',source.get(field,''))
            if (int(match[0]) if match else 0) != counts[index]:
                raise ValueError(f'CSV/wiki item mismatch: {sid}/{field}')
        required = []
        for item in cost.get(prefix+'equipment',[]):
            eid = equipment[EQUIPMENT[item['name']]]
            count,stars = item.get('count',1),item.get('level',0)
            if type(count) is not int or count<1 or type(stars) is not int or not 0<=stars<=10:
                raise ValueError(f'Invalid equipment requirement: {sid}')
            required.append({'equipment_id':eid,'name':names.items[eid]['name'],
                             'count':count,'stars_min':stars})
        routes[str(sid)] = {'source_name':source['艦名'],'target_id':tid,'target_name':target['艦名'],
                            'level':int(source['改装Lv']),'ammo':int(source['改装弾薬']),
                            'steel':int(source['改装鋼材']),'materials':counts,'equipment':required,
                            'source_record':record,'source_prefix':prefix}
    legacy = list(csv.reader((root/'data/ship_remodel_materials.csv').open(encoding='utf-8-sig')))
    differences, unmatched = [], []
    for row in legacy:
        candidates = [(sid,r) for sid,r in routes.items()
                      if normalize(r['target_name'])==normalize(row[2]) and r['level']==int(row[5])]
        if not candidates:
            unmatched.append(row[2]);continue
        old = list(map(int,row[6:]))
        matches = False
        for sid,route in candidates:
            comparable = route['materials'][:]
            comparable[8] = sum(e['count'] for e in route['equipment']
                                if e['equipment_id']==equipment['新型高温高圧缶'])
            matches = matches or comparable==old
        if not matches:
            differences.append({'target_name':row[2],'legacy_materials':old,
                                'current_routes':[{'source_id':sid,'materials':r['materials']} for sid,r in candidates]})
    convert = json.loads((root/'data/ship_convert_materials.json').read_text())
    convert_changes = []
    for sid,route in convert['routes'].items():
        fresh = routes[sid]
        if any(route[key] != fresh[key] for key in ('source_name','target_id','target_name','level')):
            raise ValueError(f'Conversion route changed: {sid}')
        if route['materials'] != fresh['materials']:
            convert_changes.append({'source_id':sid,'previous':route['materials'],'current':fresh['materials']})
        route.update({key:fresh[key] for key in ('materials','source_record','source_prefix')})
    source = f'https://github.com/kcwiki/kancolle-data/blob/{revision}/wiki/ship.json'
    digest = hashlib.sha256(payload).hexdigest()
    convert.update(source=source,sha256=digest)
    result = {'schema':1,'source':source,'sha256':digest,'routes':routes,
              'note':'Directed CSV edges cross-checked with wiki identities, level, ammo, steel and four CSV material fields. Null means unconfirmed, not zero. Equipment requirements are separate from item materials.'}
    audit = {'schema':1,'source':source,'sha256':digest,'csv_routes_checked':len(routes),
             'legacy_rows_checked':len(legacy),'legacy_numeric_differences':differences,
             'legacy_unmatched':unmatched,'convert_routes_checked':len(convert['routes']),
             'convert_changes':convert_changes,'equipment_column_reclassification':{'target':'大和改二','legacy_column':15,'equipment_id':equipment['新型高温高圧缶'],'count':2},
             'routes_with_unknown_materials':[sid for sid,r in routes.items() if None in r['materials']]}
    return result,convert,audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}',args.revision):
        parser.error('revision must be a full kcwiki commit')
    result,convert,audit=build(args.snapshot,args.revision)
    for name,data in (('ship_remodel_supplement.json',result),('ship_convert_materials.json',convert),('remodel_materials_audit.json',audit)):
        if name=='ship_remodel_supplement.json':
            header={k:v for k,v in data.items() if k!='routes'}
            text=json.dumps(header,ensure_ascii=False,indent=2)[:-2]+',\n  "routes": {\n'
            text+=',\n'.join('    '+json.dumps(sid)+': '+json.dumps(row,ensure_ascii=False,separators=(',',':'))
                             for sid,row in sorted(data['routes'].items(),key=lambda pair:int(pair[0])))
            text+='\n  }\n}\n'
        else:
            text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
        (ROOT/'data'/name).write_text(text,encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k not in ('legacy_numeric_differences','convert_changes')},ensure_ascii=False))


if __name__=='__main__':
    main()
