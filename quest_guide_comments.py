"""Short sortie-guide notes with explicit provenance; no online translation."""
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from scripts.collect_zekamashi import fleet_section_heading,select_article,visible_text,visible_walk

RULES=[
    (r'道中支援','도중지원을 활용하는 공략입니다. 지원함대의 피로·장비를 정비해 도중 돌파를 돕습니다.'),
    (r'決戦支援','결전지원을 활용하는 공략입니다. 보스전 수반함을 줄여 본대의 주간·야전 화력을 집중합니다.'),
    (r'煙幕(?:システム)?','원문 예시는 연막을 활용합니다. 사용 마스·진형과 대잠 장비를 함께 확인하세요.'),
    (r'対潜先制爆雷攻撃|先制対潜','선제대잠을 활용하는 예시입니다. 대잠 담당함과 포격·야전 담당함을 나눠 준비하세요.'),
    (r'対空カットイン','대공 컷인으로 항공전 피해를 줄이는 예시입니다. 대공 담당함을 넣되 임무의 지정함은 유지하세요.'),
    (r'三式弾.*(?:装備|採用|載せ|持たせ|積)|(?:装備|採用|載せ|持たせ|積).*三式弾','원문은 삼식탄을 활용합니다. 대지 장비를 준비하면서 항모·수반함 처리도 함께 고려하세요.'),
    (r'索敵(?:値|装備|計算)|要索敵','출격 전 색적을 계산하세요. 전탐·정찰기를 바꾸거나 퇴피하면 색적이 부족해질 수 있습니다.'),
    (r'渦潮|うずしお','와류를 경유하는 예시입니다. 전탐을 분산 장비해 연료·탄약 손실을 줄이세요.'),
    (r'魚雷カットイン|夜戦カットイン','야전 컷인을 활용하는 예시입니다. 컷인 담당함의 장비·운과 야전까지 남길 화력을 확인하세요.'),
    (r'キラ付け','원문은 키라를 활용합니다. 내구와 피로를 정비해 도중 대파를 줄이는 데 중점을 두세요.')]
NEGATIVE=r'不要|使わない|無視|いらない|不採用|必要(?:は)?(?:あり|ござい)ません|採用していません|なくても'


def source_facts(html,quest):
    """Translate only a small set of explicit tactical terms, retaining quotes.

    These are labelled rule-based excerpts in the review report, not a claim
    to translate every original paragraph. Negative/obsolete statements are
    deliberately not converted into positive recommendations.
    """
    from guide_lookup import guide_map,sortie_maps
    maps=sortie_maps(quest.get('requirements',{}));facts=[];active=False;current=maps if len(maps)==1 else []
    for node in visible_walk(select_article(html)):
        text=unicodedata.normalize('NFKC',visible_text(node)).strip()
        if node.tag=='h2':
            if active and not fleet_section_heading(text):break
            active=fleet_section_heading(text)
        if not active:continue
        if node.tag in {'h3','h4','h5'}:
            found=[guide_map(x,maps) for x in re.findall(r'[1-7]-[1-6](?:-[1-3])?',text)]
            if found:current=list(dict.fromkeys(found))
        if node.tag not in {'p','li'} or re.search(NEGATIVE+'|一期|旧編成',text):continue
        if current and maps and not any(m in maps or any(e.startswith(m+'-') for e in maps) for m in current):continue
        for pattern,korean in RULES:
            if pattern==r'渦潮|うずしお' and re.search(r'(?:渦潮|うずしお).*回避|回避.*(?:渦潮|うずしお)',text):continue
            if re.search(pattern,text) and not any(f['ko']==korean and f['maps']==current for f in facts):
                facts.append({'ko':korean,'maps':current,'quote':text[:1200],'kind':'reviewed_term_rule'})
    return facts


def reviewed_text_only(quest,root,html):
    # Code can arrive before the PC's private data sync. Never fall back to
    # sending explicitly retired photos during that interval.
    policy=Path(root)/'data/quest_guide_comment_overrides.json'
    if policy.is_file():
        try:
            if json.loads(policy.read_text(encoding='utf-8')).get(quest['wiki_id'],{}).get('text_only'):
                return True
        except (OSError,ValueError):pass
    path=Path(root)/'guide_cache/guide_audit/quest_guide_comments.json'
    if not path.is_file():return False
    try:entry=json.loads(path.read_text(encoding='utf-8')).get('quests',{}).get(quest['wiki_id'],{})
    except (OSError,ValueError):return False
    return bool(entry.get('text_only') and entry.get('html_sha256')==
                hashlib.sha256(html.replace('\r\n','\n').encode()).hexdigest())


def general_only_maps(quest,root,html):
    path=Path(root)/'guide_cache/guide_audit/quest_guide_comments.json'
    if not path.is_file():return []
    entry=json.loads(path.read_text(encoding='utf-8')).get('quests',{}).get(quest['wiki_id'],{})
    if entry.get('html_sha256')!=hashlib.sha256(html.replace('\r\n','\n').encode()).hexdigest():return []
    return entry.get('general_only_maps',[])


def notes(quest,root,*,area=None,source_html=None,allow_source=True):
    if quest.get('category')!='sortie':return []
    from guide_lookup import guide_map
    import quests
    root=Path(root);code=quest['wiki_id'];entry={}
    path=root/'guide_cache/guide_audit/quest_guide_comments.json'
    if path.is_file():
        try:entry=json.loads(path.read_text(encoding='utf-8')).get('quests',{}).get(code,{})
        except (OSError,ValueError):pass
    if allow_source and source_html is None and entry.get('html_sha256'):
        article=root/'guide_cache/zekamashi'/re.sub(r'[^A-Za-z0-9_-]','_',code)/'article.html'
        if article.is_file():source_html=article.read_text(encoding='utf-8')
    actual=hashlib.sha256(source_html.replace('\r\n','\n').encode()).hexdigest() if source_html is not None else None
    facts=entry.get('facts',[]) if allow_source and actual and actual==entry.get('html_sha256') else []
    if area:
        area=guide_map(area)
        facts=[f for f in facts if not f.get('maps') or any(m==area or area.startswith(m+'-') for m in f['maps'])]
    selected=[]
    for fact in facts:
        label=('/'.join(fact['maps'])+': ') if fact.get('maps') and not area else ''
        text=label+fact['ko']
        if text not in selected:selected.append(text)
        if len(selected)==2:break
    catalog=quests.catalog();requirements=[]
    if hasattr(catalog,'requirements'):
        try:requirements=quest.get('requirements_ko') or catalog.requirements(quest['requirements'])
        except (quests.UnsupportedCondition,KeyError,TypeError):pass
    targets=[line for line in requirements if re.search(r'보스|지점|격침|전투 \d|도달',line)]
    if area:
        targets=[line for line in targets if area in line or area[:3] in line] or targets
        narrowed=[]
        for line in targets:
            match=re.match(r'^([1-7]-[1-6](?:-[1-3])?(?:/[1-7]-[1-6](?:-[1-3])?)*)(.*)$',line)
            if match and area in [guide_map(m) for m in match[1].split('/')]:
                line=area+match[2].replace(' 각 ',' ')
            narrowed.append(line)
        targets=narrowed
    if targets:
        target=' / '.join(dict.fromkeys(targets))
        if len(target)>190:target=f'해역별 승리 등급·횟수와 선택 조건은 !임무 {code}에서 확인하세요.'
        selected.insert(0,'목표: '+target)
    if len(selected)<2:
        comp=[line for line in requirements if '+' in line or '(기함)' in line or '편성 제외' in line]
        if len(comp)==1:selected.append('편성: '+comp[0])
        elif comp:selected.append(f'여러 편성안 중 선택하는 임무입니다. 기함·지정함은 !임무 {code}를 확인하세요.')
    if not selected:selected.append(f'임무의 기함·지정함·승리 조건은 !임무 {code}를 우선하세요.')
    if len(selected)<2:selected.append(f'임무를 수락한 뒤 출격하고, 진행 조건은 !임무 {code}에서 확인하세요.')
    return selected[:3]


def block(quest,root,*,area=None,source_html=None,allow_source=True):
    lines=notes(quest,root,area=area,source_html=source_html,allow_source=allow_source)
    return '\n\n[임무·공략 메모]\n'+'\n'.join('· '+line for line in lines) if lines else ''
