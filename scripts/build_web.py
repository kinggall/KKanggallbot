"""Export an explicit, public-only static quest catalogue. No network requests."""
import json
from pathlib import Path
import re
import shutil
import sys
import unicodedata
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import quests

def load_guide_links(root,catalog):
    """Use reviewed public metadata, never private caches or a generated fallback."""
    document=json.loads((Path(root)/'data/web_guide_links.json').read_text(encoding='utf-8'))
    if document.get('schema')!=1 or not isinstance(document.get('links'),list):
        raise ValueError('Invalid reviewed public guide links')
    if not document['links'] or len(document['links'])!=document.get('expected_link_count'):
        raise ValueError('Reviewed guide count changed; review links and expected_link_count together')
    links={};codes=set()
    for entry in document['links']:
        key=entry['id'];row=catalog.items.get(key)
        if key in links or entry['code'] in codes:raise ValueError('Duplicate reviewed guide: '+key)
        if not row or row['wiki_id']!=entry['code'] or quests.normalized(row.get('name_jp',''))!=quests.normalized(entry['name_jp']):
            raise ValueError('Guide quest identity changed; review public link: '+key)
        parsed=urlparse(entry['url'])
        if (parsed.scheme!='https' or parsed.netloc!='zekamashi.net' or parsed.query or parsed.fragment
                or not re.fullmatch(r'/kancolle-kouryaku/[A-Za-z0-9_%\-/]+/',parsed.path)
                or '..' in parsed.path):
            raise ValueError('Invalid reviewed guide URL: '+key)
        if row['category']!='sortie':raise ValueError('Guide linked to non-sortie quest: '+key)
        links[key]=entry['url'];codes.add(entry['code'])
    return links

def sortie_maps(value):
    """Public map facts only; keep the web build independent of collector modules."""
    found=[]
    if isinstance(value,dict):
        for key,child in value.items():
            if key=='map':
                for item in child if isinstance(child,list) else [child]:
                    if not isinstance(item,str):continue
                    area=unicodedata.normalize('NFKC',item).strip()
                    area=quests.SORTIE_BOSS_MAPS.get(area,area)
                    area=re.sub(r'^([1-7]-[1-6])-?[A-Z]$',r'\1',area)
                    match=re.fullmatch(r'([1-7])-?([1-6])(?:-?P?([1-3]))?',area)
                    if match:found.append('-'.join(p for p in match.groups() if p))
            else:found.extend(sortie_maps(child))
    elif isinstance(value,list):
        for child in value:found.extend(sortie_maps(child))
    return list(dict.fromkeys(found))

def build(root=ROOT):
    root=Path(root);catalog=quests.QuestCatalog(root)
    links=load_guide_links(root,catalog)
    rows=[]
    for key,row in sorted(catalog.items.items(),key=lambda p:quests.natural_code(p[1]['wiki_id'])):
        rows.append({'id':key,'code':row['wiki_id'],'aliases':row.get('aliases',[]),
            'title':row['name_ko'],'titleJp':row.get('name_jp',''),
            'category':row['category'],'frequency':row['frequency'],
            'frequencyLabel':quests.FREQUENCY[row['frequency']],
            'ended':bool(row.get('unavailable')),'limited':bool(row.get('limited')),
            'releaseDate':row.get('release_date',''),'isNew':bool(row.get('source_row')),
            'detail':catalog.detail(key),'maps':sortie_maps(row.get('requirements',{})),
            'guideUrl':links.get(key),
            'before':[str(x) for x in row['prereqs'] if str(x) in catalog.items],
            'after':sorted(catalog.after.get(key,[]),key=lambda k:quests.natural_code(catalog.items[k]['wiki_id']))})
    queries=set(catalog.ship_queries)|set(catalog.commander_queries)
    unit_queries=set()
    for units in catalog.quest_units.values():
        for number,suffix in units:
            unit_queries.update(quests.normalized(prefix+str(number)+kind) for prefix in ['','제','第']
                                for kind,canonical in quests.UNIT_KINDS.items() if canonical==suffix)
    queries.update(unit_queries)
    search={q:catalog.search_keys(q) for q in sorted(queries)}
    data={'schema':1,'quests':rows,'search':{q:ids for q,ids in search.items() if ids},'unitQueries':sorted(unit_queries)}
    output=root/'web/data';output.mkdir(parents=True,exist_ok=True)
    (output/'quests.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:
        shutil.copyfile(root/name,root/'web'/name)
    print(f'Exported {len(rows)} quests, {sum(bool(r["guideUrl"]) for r in rows)} source links. No guide images or articles exported.')
    return data

if __name__=='__main__':build()
