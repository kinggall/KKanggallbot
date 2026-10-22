"""General-area guide parsing and offline previews, separate from quest guides."""
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
AREA_COUNTS = {1:6, 2:5, 3:5, 4:5, 5:6, 6:5, 7:5}
AREAS = tuple(f'{a}-{n}' for a,count in AREA_COUNTS.items() for n in range(1,count+1))
USAGE = '사용법: !공략 [해역] [루트번호/이름(선택)]\n예: !공략 55 / !공략 55 루트1 / !공략 55 중앙'


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
    groups=[]
    for example in examples:
        label=example['label']
        existing=next((g for g in groups if label and g['label']==label),None)
        if existing is None:
            existing={'number':len(groups)+1,'label':label or '기본','variants':[]}
            groups.append(existing)
        existing['variants'].append(example)
    return {'schema':1,'area':area,'title_jp':title,'url':url,'routes':groups}


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
        variants=route['variants'] if len(parts)==2 else route['variants'][:1]
        for variant in variants:
            heading=f'루트{route["number"]} · {route["label"]}'
            if len(parts)==2 and variant['phase']:heading+=' ['+variant['phase']+']'
            summary=variant['summary'] or '편성은 이미지 참조 / 경로 요약 미확인'
            match=re.search(NODE_ROUTE,summary)
            if match:summary=summary[:match.start()].strip()+'\n'+summary[match.start():]
            lines.append(heading+'\n'+summary)
            entries=list(variant['images'])
            if len(parts)==2:entries+=variant.get('airbase_images',[])
            for name in entries:
                p=folder/name
                if p.parent.resolve()!=folder.resolve() or not p.is_file():
                    return f'{area} 해역 공략\n\n공략 이미지 수집이 완료되지 않았습니다.',[]
                if p not in pictures:pictures.append(p)
    if len(parts)==1:lines.append(f'루트 선택: !공략 {area.replace("-","")} 루트1')
    lines.append('원문: '+record['url'])
    return '\n\n'.join(lines),pictures
