"""Export an explicit, public-only static quest catalogue. No network requests."""
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import quests
from guide_lookup import record_matches,article_matches,sortie_maps,GENERAL_ONLY_QUESTS

def guide_url(root,row):
    if row['wiki_id'] in GENERAL_ONLY_QUESTS:return None
    folder=root/'guide_cache/zekamashi'/re.sub(r'[^A-Za-z0-9_-]','_',row['wiki_id'])
    try:
        record=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        url=record.get('url','');parsed=urlparse(url)
        if (record.get('status')=='downloaded' and record_matches(record,row)
            and parsed.scheme=='https' and parsed.hostname=='zekamashi.net'
            and parsed.path.startswith('/kancolle-kouryaku/')
            and article_matches((folder/'article.html').read_text(encoding='utf-8'),record,row)):
            return url
    except (OSError,ValueError,KeyError):pass
    return None

def build(root=ROOT):
    root=Path(root);catalog=quests.QuestCatalog(root)
    rows=[]
    for key,row in sorted(catalog.items.items(),key=lambda p:quests.natural_code(p[1]['wiki_id'])):
        rows.append({'id':key,'code':row['wiki_id'],'aliases':row.get('aliases',[]),
            'title':row['name_ko'],'titleJp':row.get('name_jp',''),
            'category':row['category'],'frequency':row['frequency'],
            'frequencyLabel':quests.FREQUENCY[row['frequency']],
            'ended':bool(row.get('unavailable')),'limited':bool(row.get('limited')),
            'releaseDate':row.get('release_date',''),'isNew':bool(row.get('source_row')),
            'detail':catalog.detail(key),'maps':sortie_maps(row.get('requirements',{})),
            'guideUrl':guide_url(root,row) if row['category']=='sortie' else None,
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
