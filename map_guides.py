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
MULTI_GAUGES = {'5-6':3,'7-2':2,'7-3':2,'7-5':3}
USAGE = '사용법: !공략 [해역/임무번호/키워드]\n예: !공략 아호작전 / !공략 수상반격\n     !공략 By10 65 / !공략 55 중앙'


def parse_area(value):
    value = unicodedata.normalize('NFKC',value).strip()
    match = re.fullmatch(r'([1-7])-?([1-6])',value)
    area = f'{match[1]}-{match[2]}' if match else None
    return area if area in AREAS else None


def parse_map_query(value):
    """Keep collector map parsing separate from optional gauge selectors."""
    value=unicodedata.normalize('NFKC',value).strip()
    area=parse_area(value)
    if area:return area,None
    match=re.fullmatch(r'([1-7])-?([1-6])-?([1-9])',value)
    if match:
        area=f'{match[1]}-{match[2]}'
        if area in MULTI_GAUGES:return area,int(match[3])
    return None


def gauge_routes(record):
    """Build gauge-local route numbers without rewriting cached manifests."""
    tree={}
    for route in record['routes']:
        partitions={}
        for variant in route['variants']:
            match=re.fullmatch(r'(\d+)게이지',variant.get('phase',''))
            if match:partitions.setdefault(int(match[1]),[]).append(variant)
        for gauge,variants in partitions.items():
            items=tree.setdefault(gauge,[])
            label=re.sub(r'^\d+게이지(?:\s*·\s*)?','',route['label']).strip() or '기본'
            items.append(dict(route,number=len(items)+1,label=label,variants=variants))
    return dict(sorted(tree.items()))


def hidden(tag):
    for node in [tag,*tag.parents]:
        if getattr(node,'attrs',None) is None:
            continue
        if any(str(c).startswith('blogcard') for c in node.get('class',[])):
            return True
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
    if '下上ルート' in text:return '하단→상단'
    if '上中ルート' in text:return '상단→중앙'
    if '準下' in text:return '준하단'
    if '準上' in text:return '준상단'
    if '中央' in text:return '중앙'
    if re.search(r'上(?:側|回り)?ルート|上ルート|上側',text):return '상단'
    if re.search(r'下(?:側|回り)?ルート|下ルート|下側',text):return '하단'
    if '右ルート' in text:return '우측'
    if '左ルート' in text:return '좌측'
    return None


def phase_label(title):
    gauge=re.search(r'第?([1-9一二三四五六七八九])ゲージ',unicodedata.normalize('NFKC',title))
    if gauge:
        number=str('一二三四五六七八九'.index(gauge[1])+1) if gauge[1] in '一二三四五六七八九' else gauge[1]
        return number+'게이지'
    if 'ゲージ破壊前' in title:return '게이지 파괴 전'
    if 'ゲージ破壊後' in title:return '게이지 파괴 후'
    if '削り' in title:return '게이지 공략 중'
    if 'ラスト' in title or '最終形態' in title:return '최종 형태'
    return ''


def extract(html,area,url):
    """Keep visible fleet examples, raw notes, and distinct base-air images."""
    from scripts.collect_zekamashi import image_identity, image_source_url
    from guide_lookup import FLEET_TYPES,find_route,find_random_fleet,translate_route
    soup=BeautifulSoup(html,'html.parser')
    body=soup.select_one('.entry-content, .post-content, .entry__body, .post_content, .entry__content')
    h1=soup.find('h1')
    title=h1.get_text(' ',strip=True) if h1 else ''
    normalized=unicodedata.normalize('NFKC',title)
    if not body or not re.search(r'(?<!\d)'+re.escape(area)+r'(?!\d)',normalized):
        raise ValueError('Area title/body does not match requested map: '+area)
    if '一期' in title:
        raise ValueError('Outdated Phase 1 article')
    examples=[];current=None;hierarchy={};airbase=False;reference=False;active_level=0
    for tag in body.find_all(['h2','h3','h4','h5','p','li','img','table']):
        if hidden(tag):continue
        if tag.name.startswith('h') and tag.name[1:].isdigit():
            level=int(tag.name[1]);text=tag.get_text(' ',strip=True)
            hierarchy={k:v for k,v in hierarchy.items() if k<level};hierarchy[level]=text
            context=' / '.join(hierarchy.values())
            if current and '基地航空隊' in text:
                airbase=True;reference=False
                continue
            if current and airbase and '初めて攻略する際の例' in text and '仮置' in text:
                # Preserve the provisional beginner base in reference data,
                # not among the base images sent with the current fleet.
                reference=True;airbase=False
                continue
            if current and ('資料' in text or '条件について' in text):
                reference=True;airbase=False
                continue
            is_example=bool(('編成例' in text or ('基地航空隊' not in context and
                            re.search(r'初攻略での編成案|初めて攻略する際の例',text)))
                            and not re.search(r'旧編成|過去|一期|支援',context))
            if is_example:
                current={'source_heading':context,'label':route_label(context),
                         'phase':phase_label(context),'summary':'','notes_jp':[],
                         'images':[],'airbase_images':[],'airbase_notes_jp':[]}
                examples.append(current);active_level=level;airbase=False;reference=False
            elif current:
                fleet_heading=bool(re.match(r'^'+FLEET_TYPES+r'\s*\d',unicodedata.normalize('NFKC',text)))
                if level<=active_level:
                    current=None;airbase=False;reference=False
                elif '基地航空隊' in text:
                    airbase=True
                elif route_label(text) or phase_label(text) or fleet_heading:
                    if current['summary'] or current['images']:
                        current={'source_heading':context,'label':route_label(context),
                                 'phase':phase_label(context),'summary':'','notes_jp':[],
                                 'images':[],'airbase_images':[],'airbase_notes_jp':[]}
                        examples.append(current)
                    airbase=False;reference=False
                    if fleet_heading:current['fleet_heading']=text
            continue
        if not current:continue
        if tag.name=='img':
            anchor=tag.find_parent('a');href=urljoin(url,anchor.get('href','')) if anchor else ''
            src=href if re.search(r'\.(png|jpe?g|webp)(?:\?|$)',href,re.I) else urljoin(url,tag.get('data-src') or tag.get('src',''))
            src=image_source_url(src)
            if urlparse(src).hostname!='zekamashi.net' or '/wp-content/uploads/' not in src:continue
            key='reference_image_urls' if reference else 'airbase_images' if airbase else 'images'
            current.setdefault(key,[])
            if not any(image_identity(x)==image_identity(src) for x in current[key]):current[key].append(src)
        elif tag.name in {'p','li','table'}:
            # Lists inside a paragraph/table are still preserved as raw notes;
            # keep a unique entry to avoid repeating the same source text.
            text=unicodedata.normalize('NFKC',tag.get_text(' ',strip=True))
            key='reference_notes_jp' if reference else 'airbase_notes_jp' if airbase else 'notes_jp'
            current.setdefault(key,[])
            if text and text not in current[key]:current[key].append(text)
            if not airbase and not reference and not current['summary']:
                # Some articles give the fleet only in the section heading,
                # then start their table with a bare node chain.
                heading_fleet=re.search(FLEET_TYPES+r'(?:級)?\s*\d.*',current['source_heading'].rsplit(' / ',1)[-1])
                candidate=text
                if re.match(r'^(?:編成とルート\s*)?【',text) and heading_fleet:
                    fleet=heading_fleet.group().split('【',1)[0].strip()
                    candidate=fleet+' '+re.sub(r'^編成とルート\s*','',text)
                route=find_route(candidate)
                summary=translate_route(route) if route else find_random_fleet(text)
                if route:
                    from guide_lookup import NODE_ROUTE
                    route_matches=list(re.finditer(NODE_ROUTE,text.split('ルート条件')[0]))
                    fleet=route.split('【',1)[0]
                    for extra in route_matches[1:]:
                        extra_route=find_route(fleet+text[extra.start():])
                        if extra_route:
                            summary+='\n'+translate_route(extra_route[len(fleet):]).strip()
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
        if re.fullmatch(r'\d+게이지',example['phase']):
            label=example['phase']+(' · '+label if label else '')
        node_route=re.search(r'【[^】]+】',example['summary'])
        # Different paths within one gauge still require separate choices.
        key=((label,node_route.group() if node_route else None)
             if label and '게이지' in label else label or (node_route.group() if node_route else None))
        existing=next((g for g in groups if key and g.get('_key')==key),None)
        if existing is None and not label and node_route:
            existing=next((g for g in groups if any(
                re.search(r'【[^】]+】',v['summary']) and
                re.search(r'【[^】]+】',v['summary']).group()==node_route.group()
                for v in g['variants'])),None)
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
        if 'ボス前ランダム' in text and '※ 보스 전 분기 랜덤' not in output:
            output.append('※ 보스 전 분기 랜덤')
        branch=re.search(r'([A-Z])[→⇒]([A-Z])の確率が\s*(\d+(?:\.\d+)?)%',text)
        if branch:
            line=f'※ {branch[1]}→{branch[2]} 확률 {branch[3]}%'
            random_node=re.search(r'([A-Z])マスはランダムで経由',text)
            if random_node:line+=f' / {random_node[1]} 랜덤 경유'
            if line not in output:output.append(line)
        boss_rate=re.search(r'ボス率\s*(\d+(?:\.\d+)?)%程度',text)
        if boss_rate:
            line=f'※ 보스 도달률 약 {boss_rate[1]}%'
            if line not in output:output.append(line)
        elif re.search(r'ルート固定していない|ルート固定不可|固定なしの例',text):
            if '※ 경로가 고정되지 않은 편성입니다.' not in output:
                output.append('※ 경로가 고정되지 않은 편성입니다.')
        conditions=re.search(r'ルート条件\s*(.*?)(?=陣形選択|制空値|コメント|$)',text)
        if conditions:
            rule=re.sub(r'\s+','',conditions[1])
            requirements=[]
            speed=re.search(r'(?:^|[、,。※])(?:要)?(高速\+?統一)(?=[、,。※]|$)',rule)
            if speed:requirements.append('고속+통일' if '+' in speed[1] else '고속통일')
            radar=re.search(r'電探を(\d+)つ以上装備',rule)
            if radar:requirements.append(f'전탐 {radar[1]}개 이상')
            search=re.search(r'分岐点係数(\d+)で(?:索敵(?:値)?)?(\d+(?:\.\d+)?)以上',rule)
            if search:requirements.append(f'색적 {search[2]} 이상(33식·계수{search[1]})')
            elif '要索敵' in rule:requirements.append('색적 필요')
            if requirements:
                line='※ '+' / '.join(requirements)
                if line not in output:output.append(line)
    return output


def preview(query,root=ROOT,*,cache_root=None):
    from guide_lookup import NODE_ROUTE
    parts=query.split();target=parse_map_query(parts[0]) if parts else None
    if not target or len(parts)>2:return USAGE,[]
    area,gauge=target
    folder=(Path(cache_root) if cache_root else Path(root)/'guide_cache/zekamashi_maps')/area
    path=folder/'manifest.json'
    if not path.exists():return f'{area} 해역 공략\n\n아직 수집된 일반해역 공략이 없습니다.',[]
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('area')!=area or record.get('status')!='downloaded':
        return f'{area} 해역 공략\n\n공략 수집 또는 구조 확인 중입니다.',[]
    tree=gauge_routes(record) if area in MULTI_GAUGES else {}
    if area in MULTI_GAUGES and not tree:
        return f'{area} 해역 공략\n\n게이지별 공략 구조 확인 중입니다.',[]
    if tree and gauge is None:
        compact=area.replace('-','')
        if len(parts)>1:
            first=next(iter(tree));selector='루트1' if len(tree[first])>1 else '상세'
            return f'{area} 해역 공략\n\n게이지를 먼저 선택해주세요.\n예: !공략 {compact}{first} {selector}',[]
        lines=[f'{area} 해역 공략'];pictures=[]
        for stage,routes in tree.items():
            lines.append(f'[{stage}게이지]')
            for route in routes:
                variant=route['variants'][0]
                summary=variant['summary'];match=re.search(NODE_ROUTE,summary)
                if match:summary=summary[:match.start()].strip()+'\n'+summary[match.start():]
                label=' · '+route['label'] if route['label']!='기본' else ''
                lines.append((f'루트{route["number"]}{label}: ' if len(routes)>1 else '')+summary)
                for name in variant['images']:
                    p=folder/name
                    if p.parent.resolve()!=folder.resolve() or not p.is_file():
                        return f'{area} 해역 공략\n\n공략 이미지 수집이 완료되지 않았습니다.',[]
                    if p not in pictures:pictures.append(p)
            selector='루트1' if len(routes)>1 else '상세'
            lines.append(f'상세공략: !공략 {compact}{stage} {selector}')
        return '\n\n'.join(lines),pictures
    if gauge is not None and gauge not in tree:
        return f'{area} 해역 공략\n\n등록된 게이지: '+ ' / '.join(str(n) for n in tree)+f'\n예: !공략 {area.replace("-","")}1',[]
    routes=tree[gauge] if gauge is not None else record['routes'];selected=routes
    multiple=len(routes)>1
    numbered=multiple
    detailed=len(parts)==2
    if not numbered and detailed and parts[1]!='상세':
        return '',[]
    if detailed and parts[1]!='상세':
        selector=parts[1].lower();number=re.fullmatch(r'(?:루트|route)?(\d+)',selector)
        aliases={'중앙(하단)':{'중앙','중앙하단','중하단','중하','중앙(하단)'},
                 '중앙':{'중앙','중단'},'상단':{'상단','위','위쪽','상'},
                 '하단':{'하단','아래','아래쪽','하'},'우측':{'우측','오른쪽'},'좌측':{'좌측','왼쪽'}}
        aliases.update({'준하단':{'준하단','준하'},'준상단':{'준상단','준상'}})
        aliases.update({'하단→상단':{'하단→상단','하상','하단상단'},
                        '상단→중앙':{'상단→중앙','상중','상단중앙'}})
        selected=[r for r in routes if (number and r['number']==int(number[1])) or
                  (not number and selector in aliases.get(r['label'],{r['label']}))]
        if not selected:return f'{area} 해역 공략\n\n해당 루트가 없습니다.\n'+ '\n'.join(f'· 루트{r["number"]}: {r["label"]}' for r in routes)+'\n'+USAGE,[]
    lines=[f'{area} 해역 공략'+(f' [{gauge}게이지]' if gauge is not None else '')];pictures=[]
    for route in selected:
        variants=route['variants'] if detailed or not multiple else route['variants'][:1]
        for variant in variants:
            heading=(f'루트{route["number"]}'+(' · '+route['label'] if route['label']!='기본' else '')) if numbered else ''
            if (len(parts)==2 or not multiple) and variant['phase'] and variant['phase'] not in heading and not re.fullmatch(r'\d+게이지',variant['phase']):
                heading+=(' ' if heading else '')+'['+variant['phase']+']'
            elif len(variants)>1:
                source=variant.get('source_heading','')
                purpose='반복 출격' if '周回' in source else '최초 공략' if '初攻略' in source else '편성 '+str(variants.index(variant)+1)
                heading+=(' ' if heading else '')+'['+purpose+']'
            summary=variant['summary'] or '편성은 이미지 참조 / 경로 요약 미확인'
            match=re.search(NODE_ROUTE,summary)
            if match:summary=summary[:match.start()].strip()+'\n'+summary[match.start():]
            if detailed:
                from map_guide_details import detail_lines
                notes=detail_lines(area,variant,root)
            else:notes=[]
            lines.append((heading+'\n' if heading else '')+summary+
                         ('\n'+'\n'.join(notes) if notes else ''))
            entries=list(variant['images'])
            if detailed:entries+=variant.get('airbase_images',[])
            for name in entries:
                p=folder/name
                if p.parent.resolve()!=folder.resolve() or not p.is_file():
                    return f'{area} 해역 공략\n\n공략 이미지 수집이 완료되지 않았습니다.',[]
                # Keep fleet/base pairs together even when two examples share
                # the same airbase image (notably the lower route at 6-5).
                if detailed or p not in pictures:pictures.append(p)
    code=area.replace('-','')+(str(gauge) if gauge is not None else '')
    if numbered and not detailed:lines.append(f'상세공략: !공략 {code} 루트1' if gauge is not None else f'루트 선택: !공략 {code} 루트1')
    elif not multiple and not detailed:lines.append(f'상세공략: !공략 {code} 상세')
    return '\n\n'.join(lines),pictures
