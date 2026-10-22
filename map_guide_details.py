"""Reviewed Korean route notes and route-scoped air power references.

Zekamashi values take priority. The user's first-sheet CSV remains in the
private guide cache, not in Git. No network requests are made during lookup.
"""
import csv
import hashlib
import json
import re
from pathlib import Path


def reference_rows(path):
    if not path.is_file():return []
    rows=[]
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for row_number,cells in enumerate(csv.reader(stream),1):
            if len(cells)<6:continue
            match=re.match(r'^([1-7]-[1-6])(?:-([123]))?(?!\d)',cells[0])
            if not match or '-기믹' in cells[0] or '-M' in cells[0]:continue
            area,gauge=match.groups()
            # Text such as "제공 60 이상 추천" is not an exact threshold.
            values={name:list(map(int,re.findall(r'\d+',text))) if not re.search('[가-힣]',text) else []
                    for name,text in zip(['parity','superiority','supremacy'],cells[2:5])}
            # "Q67% /33%" is enemy-pattern probability, not a node Q67.
            nodes=re.findall(r'[A-Z]\d*',re.sub(r'\d+(?:\.\d+)?\s*%','',cells[1]))
            if not nodes and area=='7-5' and gauge=='3':nodes=['A']
            stage_groups=None
            if len(nodes)==1 and area in {'4-5','5-5','7-2','5-6'}:
                if area=='5-5':stage_groups=[('공략 중',[0]),('격파 후',[1])]
                elif area=='7-2' and gauge=='2':stage_groups=[('공략 중',[0]),('최종',[1])]
                elif area=='4-5' or area=='5-6' and gauge=='2':stage_groups=[('공략 중',[0]),('최종',[1])]
                elif area=='5-6' and gauge=='3':stage_groups=[('공략 중',[0,1]),('최종',[2,3])]
            for i,node in enumerate(nodes):
                groups=stage_groups or [('',list(range(max([len(v) for v in values.values()]+[0]))) if len(nodes)==1 else [i])]
                for phase,indexes in groups:
                    entry={'area':area,'gauge':gauge,'node':node,'phase':phase,'source':'통합공략 첫 시트','sheet_row':row_number}
                    for name,nums in values.items():
                        selected=[nums[j] for j in indexes if j<len(nums)]
                        if not selected and len(nums)==1:selected=nums
                        if selected:entry[name]=max(selected)
                    if any(k in entry for k in values):rows.append(entry)
            if cells[5]:rows.append({'area':area,'gauge':gauge,'search_text':cells[5],
                                       'fleet_text':cells[6] if len(cells)>6 else '',
                                       'source':'통합공략 첫 시트','sheet_row':row_number})
    return rows


def route_nodes(summary):
    chains=re.findall(r'【([^】]+)】',summary)
    return set(re.findall(r'[A-Z]\d*',' '.join(chains)))


def merge_air(primary,fallback):
    """Never attach a conflicting sheet field to a Zekamashi threshold."""
    merged=dict(primary)
    conflicts=[k for k in ('superiority','supremacy','parity')
               if k in primary and k in fallback and primary[k]!=fallback[k]]
    if not conflicts:
        for key in ('superiority','supremacy','parity'):
            if key not in merged and key in fallback:
                merged[key]=fallback[key]
                merged.setdefault('supplemented',[]).append(key)
    if conflicts:merged['conflicts']=conflicts
    return merged


def air_entries(area,variant,review,reference):
    gauge=re.search(r'(\d+)게이지',variant.get('phase',''))
    gauge=gauge[1] if gauge else None
    nodes=route_nodes(variant['summary'])
    # Random-routing examples do not promise a single chain. Only the nodes
    # explicitly reviewed as possible for this example may be included.
    if not nodes:nodes=set(review.get('random_nodes',[]))
    primary=[dict(e,source='zekamashi') for e in review.get('air',[])
             if str(e.get('gauge') or '')==str(gauge or '') and e['node'] in nodes]
    fallback=[e for e in reference if e['area']==area and 'node' in e
              and str(e.get('gauge') or '')==str(gauge or '') and e['node'] in nodes]
    result=[];consumed=set()
    for entry in primary:
        matches=[(i,e) for i,e in enumerate(fallback)
                 if e['node']==entry['node'] and e.get('phase','')==entry.get('phase','')]
        if matches:
            i,sheet=matches[0];entry=merge_air(entry,sheet);consumed.add(i)
        result.append(entry)
    for i,entry in enumerate(fallback):
        if i in consumed:continue
        # An unphased primary describes the reviewed worst enemy pattern;
        # don't add unrelated unnamed sheet patterns as extra stages.
        if any(e['node']==entry['node'] and not e.get('phase') for e in primary):continue
        result.append(entry)
    return result


def air_lines(entries,bosses):
    """Show the boss baseline and only higher en-route bottlenecks."""
    phases=list(dict.fromkeys(e.get('phase','') for e in entries));lines=[]
    if any(phases):phases=[p for p in phases if p]
    phases.sort(key=lambda p:{'':0,'공략 중':1,'최종':2,'격파 후':3}.get(p,4))
    for phase in phases:
        candidates=[e for e in entries if e.get('phase','') in {phase,''}]
        boss=[e for e in candidates if e['node'] in bosses]
        def score(e):return e.get('superiority',0),e.get('supremacy',0),e.get('parity',0)
        baseline=max(boss,key=score) if boss else None
        highest=max(candidates,key=score) if candidates else None
        selected=([baseline] if baseline else [])
        if highest and highest is not baseline and (not baseline or score(highest)>score(baseline)):
            selected.append(highest)
        # Partial rows (e.g. 7-4 air raid parity only) cannot be compared by
        # missing superiority; retain qualifying known parity explicitly.
        selected.extend(e for e in candidates if e not in selected and e.get('parity',0)>=100
                        and 'superiority' not in e)
        for entry in selected:
            tiers=[]
            for key,label in [('superiority','우세'),('supremacy','확보'),('parity','균형')]:
                value=entry.get(key)
                if value and (key!='parity' or value>=100):tiers.append(f'{label} {value}')
            if not tiers:continue
            node='' if entry['node'] in bosses else entry['node']
            if node:node+=('('+entry['name']+')') if entry.get('name') else '마스'
            phase_text=entry.get('phase','')
            line='· '+(node+' ' if node else '')+'제공'+('('+phase_text+')' if phase_text else '')+': '+' / '.join(tiers)
            if line not in lines:lines.append(line)
    return lines


def detail_lines(area,variant,root):
    from map_guides import translated_branch_notes
    root=Path(root);path=root/'data/map_guide_reviewed.json'
    review=json.loads(path.read_text(encoding='utf-8')).get('maps',{}).get(area,{}) if path.is_file() else {}
    source=root/'guide_cache/zekamashi_maps'/area/'article.html'
    if review.get('source_html_sha256'):
        actual=hashlib.sha256(source.read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest() if source.is_file() else None
        if actual!=review['source_html_sha256']:
            return ['· 원문이 변경되어 상세 공략을 재검토 중입니다.']
    reference=reference_rows(root/'guide_cache/map_reference/integrated_first_sheet.csv')
    entries=air_entries(area,variant,review,reference)
    bosses=set(re.findall(r'([A-Z]\d*):보스',variant['summary']))
    if not bosses:bosses=set(review.get('boss_nodes',[]))
    lines=air_lines(entries,bosses)
    # Search conditions sometimes precede the "route conditions" table cell.
    raw=' '.join([variant.get('source_heading',''),*variant.get('notes_jp',[])])
    before_comment=re.split(r'コメント|一言',raw)[0]
    requirements=[]
    search=re.search(r'分岐点係数\s*(\d+)で(?:索敵(?:値)?)?\s*(\d+(?:\.\d+)?)(?:\([^)]*\))?以上',before_comment)
    if search:requirements.append(f'색적 {search[2]} 이상(33식·계수{search[1]})')
    rule=re.search(r'ルート条件(.*?)(?=陣形選択|制空値|$)',before_comment)
    speed=re.search(r'要\s*高速(\+)?統一',rule[1]) if rule else None
    if speed:
        label='고속+통일' if speed[1] else '고속통일'
        if label not in variant['summary']:requirements.append(label)
    for note in translated_branch_notes([variant.get('source_heading',''),*variant.get('notes_jp',[])]):
        for bit in note.removeprefix('※ ').split(' / '):
            if bit.startswith('색적') and search:continue
            if bit in {'고속통일','고속+통일'} and bit in variant['summary']:continue
            if bit not in requirements:requirements.append(bit)
    if not search:
        supplement=search_fallback(area,variant,review,reference)
        if supplement:requirements=[r for r in requirements if r!='색적 필요']
        requirements.extend(supplement)
    notes=review.get('variant_notes',{}).get(variant.get('source_heading'),review.get('notes',[]))
    if requirements:lines.append('· '+' / '.join(dict.fromkeys(requirements)))
    lines.extend('· '+n for n in notes)
    return lines[:5]


def search_fallback(area,variant,review,reference):
    """Only reviewed, route-specific sheet conditions may be used as fallback."""
    selected=review.get('sheet_search',{}).get(variant.get('source_heading'))
    if not selected:return []
    nodes=route_nodes(variant['summary'])
    if selected.get('node') and selected['node'] not in nodes:return []
    # Require the exact sheet source text reviewed by the maintainer.
    if any(e.get('search_text')==selected['evidence']
           and (not selected.get('fleet_evidence') or selected['fleet_evidence'] in e.get('fleet_text',''))
           for e in reference if e['area']==area):
        return [selected['text']]
    return []
