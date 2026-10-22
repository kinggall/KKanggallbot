"""General-area guide parsing and offline previews, separate from quest guides."""
import json
import hashlib
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
AREA_COUNTS = {1:6, 2:5, 3:5, 4:5, 5:6, 6:5, 7:5}
AREAS = tuple(f'{a}-{n}' for a,count in AREA_COUNTS.items() for n in range(1,count+1))
USAGE = '사용법: !공략 [임무번호/해역]\n예: !공략 By10 / !공략 By10 65\n     !공략 55 / !공략 55 중앙'


def parse_area(value):
    value = unicodedata.normalize('NFKC',value).strip()
    match = re.fullmatch(r'([1-7])-?([1-6])',value)
    area = f'{match[1]}-{match[2]}' if match else None
    return area if area in AREAS else None


def hidden(tag):
    for node in [tag,*tag.parents]:
        if not getattr(node,'attrs',None):
            continue
        style = re.sub(r'\s+','',node.get('style','')).lower()
        if (node.has_attr('hidden') or node.get('aria-hidden')=='true'
                or (node.name=='details' and not node.has_attr('open'))
                or 'su-spoiler-closed' in node.get('class',[])
                or 'display:none' in style or 'visibility:hidden' in style):
            return True
    return False


def route_label(title):
    text=unicodedata.normalize('NFKC',title)
    if re.search(r'中央.*?下|中下',text):return '중앙(하단)'
    if '中央' in text:return '중앙'
    if re.search(r'上(?:側|回り)?ルート|上ルート|上側',text):return '상단'
    if re.search(r'下(?:側|回り)?ルート|下ルート|下側',text):return '하단'
    if '右ルート' in text:return '우측'
    if '左ルート' in text:return '좌측'
    return None


def phase_label(title):
    if 'ゲージ破壊前' in title:return '게이지 파괴 전'
    if 'ゲージ破壊後' in title:return '게이지 파괴 후'
    if '削り' in title:return '게이지 공략 중'
    if 'ラスト' in title or '最終形態' in title:return '최종 형태'
    return ''


def extract(html,area,url):
    """Keep visible fleet examples, raw notes, and distinct base-air images."""
    from scripts.collect_zekamashi import image_identity, image_source_url
    from guide_lookup import find_route,find_random_fleet,translate_route
    soup=BeautifulSoup(html,'html.parser')
    body=soup.select_one('.entry-content, .post-content, .entry__body, .post_content, .entry__content')
    h1=soup.find('h1')
    title=h1.get_text(' ',strip=True) if h1 else ''
    normalized=unicodedata.normalize('NFKC',title)
    if not body or not re.search(r'(?<!\d)'+re.escape(area)+r'(?!\d)',normalized):
        raise ValueError('Area title/body does not match requested map: '+area)
    if '一期' in title:
        raise ValueError('Outdated Phase 1 article')
    examples=[];current=None;hierarchy={};airbase=False;active_level=0
    for tag in body.find_all(['h2','h3','h4','h5','p','li','img','table']):
        if hidden(tag):continue
        if tag.name.startswith('h') and tag.name[1:].isdigit():
            level=int(tag.name[1]);text=tag.get_text(' ',strip=True)
            hierarchy={k:v for k,v in hierarchy.items() if k<level};hierarchy[level]=text
            context=' / '.join(hierarchy.values())
            if current and '基地航空隊' in text:
                airbase=True
                continue
            is_example='編成例' in text and not re.search(r'旧編成|過去|一期',context)
            if is_example:
                current={'source_heading':context,'label':route_label(context),
                         'phase':phase_label(context),'summary':'','notes_jp':[],
                         'images':[],'airbase_images':[],'airbase_notes_jp':[]}
                examples.append(current);active_level=level;airbase=False
            elif current:
                if level<=active_level:
                    current=None;airbase=False
                elif '基地航空隊' in text:
                    airbase=True
                elif route_label(text) or phase_label(text):
                    if current['summary'] or current['images']:
                        current={'source_heading':context,'label':route_label(context),
                                 'phase':phase_label(context),'summary':'','notes_jp':[],
                                 'images':[],'airbase_images':[],'airbase_notes_jp':[]}
                        examples.append(current)
                    airbase=False
            continue
        if not current:continue
        if tag.name=='img':
            anchor=tag.find_parent('a');href=urljoin(url,anchor.get('href','')) if anchor else ''
            src=href if re.search(r'\.(png|jpe?g|webp)(?:\?|$)',href,re.I) else urljoin(url,tag.get('data-src') or tag.get('src',''))
            src=image_source_url(src)
            if urlparse(src).hostname!='zekamashi.net' or '/wp-content/uploads/' not in src:continue
            key='airbase_images' if airbase else 'images'
            if not any(image_identity(x)==image_identity(src) for x in current[key]):current[key].append(src)
        elif tag.name in {'p','li','table'}:
            # Lists inside a paragraph/table are still preserved as raw notes;
            # keep a unique entry to avoid repeating the same source text.
            text=unicodedata.normalize('NFKC',tag.get_text(' ',strip=True))
            key='airbase_notes_jp' if airbase else 'notes_jp'
            if text and text not in current[key]:current[key].append(text)
            if not airbase and not current['summary']:
                route=find_route(text)
                summary=translate_route(route) if route else find_random_fleet(text)
                if summary:current['summary']=summary
    examples=[e for e in examples if e['summary'] or e['images']]
    if not examples:raise ValueError('No visible fleet examples found; manual review required')
    corrections=ROOT/'data/map_guide_overrides.json'
    reviewed=json.loads(corrections.read_text(encoding='utf-8')).get(area,{}) if corrections.exists() else {}
    if reviewed.get('html_sha256')==hashlib.sha256(html.replace('\r\n','\n').encode()).hexdigest():
        for example in examples:
            for correction in reviewed.get('fleets',[]):
                if (example['source_heading']==correction['heading']
                        and example['summary'].startswith(correction['original'])):
                    example['summary']=correction['replacement']+example['summary'][len(correction['original']):]
                    example['reviewed_correction']=correction['reason']
    groups=[]
    for example in examples:
        label=example['label']
        node_route=re.search(r'【[^】]+】',example['summary'])
        key=label or (node_route.group() if node_route else None)
        existing=next((g for g in groups if key and g.get('_key')==key),None)
        if existing is None:
            existing={'number':len(groups)+1,'label':label or '기본','variants':[],'_key':key}
            groups.append(existing)
        existing['variants'].append(example)
    for group in groups:group.pop('_key',None)
    return {'schema':1,'area':area,'title_jp':title,'url':url,'routes':groups}


def translated_branch_notes(notes):
    """Translate explicit branch probabilities without inferring fixed routing."""
    output=[]
    for raw in notes:
        text=unicodedata.normalize('NFKC',raw)
        probabilities=list(re.finditer(r'([A-Z])側に\s*(\d+(?:\.\d+)?)%\s*(で逸れあり)?',text))
        if probabilities:
            parts=[f'{m[1]} '+('이탈' if m[3] else '진입')+f' {m[2]}%' for m in probabilities]
            line='※ '+' / '.join(parts)
            if line not in output:output.append(line)
        elif '低確率で逸れあり' in text:
            if '※ 낮은 확률로 이탈할 수 있습니다.' not in output:
                output.append('※ 낮은 확률로 이탈할 수 있습니다.')
    return output


def preview(query,root=ROOT,*,cache_root=None):
    from guide_lookup import NODE_ROUTE
    parts=query.split();area=parse_area(parts[0]) if parts else None
    if not area or len(parts)>2:return USAGE,[]
    folder=(Path(cache_root) if cache_root else Path(root)/'guide_cache/zekamashi_maps')/area
    path=folder/'manifest.json'
    if not path.exists():return f'{area} 해역 공략\n\n아직 수집된 일반해역 공략이 없습니다.',[]
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('area')!=area or record.get('status')!='downloaded':
        return f'{area} 해역 공략\n\n공략 수집 또는 구조 확인 중입니다.',[]
    routes=record['routes'];selected=routes
    multiple=len(routes)>1
    if not multiple and len(parts)==2:
        return '',[]
    if len(parts)==2:
        selector=parts[1].lower();number=re.fullmatch(r'(?:루트|route)?(\d+)',selector)
        aliases={'중앙(하단)':{'중앙','중앙하단','중하단','중하','중앙(하단)'},
                 '중앙':{'중앙','중단'},'상단':{'상단','위','위쪽','상'},
                 '하단':{'하단','아래','아래쪽','하'},'우측':{'우측','오른쪽'},'좌측':{'좌측','왼쪽'}}
        selected=[r for r in routes if (number and r['number']==int(number[1])) or
                  (not number and selector in aliases.get(r['label'],{r['label']}))]
        if not selected:return f'{area} 해역 공략\n\n해당 루트가 없습니다.\n'+ '\n'.join(f'· 루트{r["number"]}: {r["label"]}' for r in routes)+'\n'+USAGE,[]
    lines=[f'{area} 해역 공략'];pictures=[]
    for route in selected:
        variants=route['variants'] if len(parts)==2 or not multiple else route['variants'][:1]
        for variant in variants:
            heading=f'루트{route["number"]} · {route["label"]}' if multiple else ''
            if (len(parts)==2 or not multiple) and variant['phase']:
                heading+=(' ' if heading else '')+'['+variant['phase']+']'
            elif not multiple and len(variants)>1:
                source=variant.get('source_heading','')
                purpose='반복 출격' if '周回' in source else '최초 공략' if '初攻略' in source else '편성 '+str(variants.index(variant)+1)
                heading='['+purpose+']'
            summary=variant['summary'] or '편성은 이미지 참조 / 경로 요약 미확인'
            match=re.search(NODE_ROUTE,summary)
            if match:summary=summary[:match.start()].strip()+'\n'+summary[match.start():]
            notes=translated_branch_notes(variant.get('notes_jp',[]))
            lines.append((heading+'\n' if heading else '')+summary+
                         ('\n'+'\n'.join(notes) if notes else ''))
            entries=list(variant['images'])
            if len(parts)==2:entries+=variant.get('airbase_images',[])
            for name in entries:
                p=folder/name
                if p.parent.resolve()!=folder.resolve() or not p.is_file():
                    return f'{area} 해역 공략\n\n공략 이미지 수집이 완료되지 않았습니다.',[]
                if p not in pictures:pictures.append(p)
    if multiple and len(parts)==1:lines.append(f'루트 선택: !공략 {area.replace("-","")} 루트1')
    return '\n\n'.join(lines),pictures
