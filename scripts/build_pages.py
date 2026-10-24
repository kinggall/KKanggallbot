"""Fail-closed Cloudflare Pages build, using stdlib and tracked public inputs only."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import build_web

PUBLIC_FILES={'index.html','style.css','navigation.css','app.js','_headers','data/quests.json','LICENSE','THIRD_PARTY_NOTICES.md'}
PUBLIC_FIELDS={'id','code','aliases','title','titleJp','category','frequency','frequencyLabel','ended','limited','releaseDate','isNew','detail','maps','guideUrl','before','after'}

def unique_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key: '+key)
        result[key]=value
    return result

def validate_directory(folder):
    folder=Path(folder)
    if any(p.is_symlink() for p in folder.rglob('*')):raise ValueError('Public directory contains a symlink')
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    if actual!=PUBLIC_FILES:raise ValueError('Unexpected/missing public files: '+str(actual^PUBLIC_FILES))
    for path in folder.rglob('*'):
        if path.is_file():
            text=path.read_text(encoding='utf-8')
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"(?:refresh_token|client_secret|private_key)"\s*:',text):
                raise ValueError('Credential-like data in public file: '+path.name)

def validate_data(data):
    if data.get('schema')!=1 or not data.get('quests'):raise ValueError('Empty/invalid public catalogue')
    ids=set();codes={}
    for row in data['quests']:
        if set(row)!=PUBLIC_FIELDS or row['id'] in ids:raise ValueError('Invalid/duplicate public quest')
        if not row['title'].strip() or not row['code'].strip() or not row['detail'].strip():raise ValueError('Missing quest content')
        ids.add(row['id'])
        for code in [row['code'],*row['aliases']]:
            key=build_web.quests.normalized(code)
            if key in codes and codes[key]!=row['id']:raise ValueError('Conflicting public quest code: '+code)
            codes[key]=row['id']
    for row in data['quests']:
        if not set(row['before']+row['after'])<=ids:raise ValueError('Broken prerequisite/successor link')
    for found in data['search'].values():
        if not set(found)<=ids:raise ValueError('Broken search index')

def validate_continuity(previous,current):
    old_ids={row['id'] for row in previous['quests']}
    new_ids={row['id'] for row in current['quests']}
    if old_ids-new_ids:
        raise ValueError('Published quests disappeared; review removal and explicitly update snapshot: '+str(sorted(old_ids-new_ids)))

def run(root=ROOT):
    root=Path(root)
    validate_directory(root/'web')
    previous=json.loads((root/'web/data/quests.json').read_text(encoding='utf-8'),object_pairs_hook=unique_keys)
    validate_data(previous)
    subprocess.run(['node','--check',str(root/'web/app.js')],check=True)
    for name in ['quests.json','quest_wiki_updates.json','ship_aliases.json','quest_commanders.json','web_guide_links.json']:
        path=root/'data'/name
        if path.exists():json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique_keys)
    data=build_web.build(root)
    validate_data(data)
    validate_continuity(previous,data)
    validate_directory(root/'web')
    print('PASS: public output allowlist, quest identity, codes, links, search references, credential checks')
    return data

if __name__=='__main__':
    run()
    for test in ['test_web_export.py','test_web_automation.py']:
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p',test,'-v'],cwd=ROOT,check=True)
