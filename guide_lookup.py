"""Preview composition summaries from locally collected Zekamashi guides."""
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import quests
from scripts.collect_zekamashi import Document, fleet_section_heading, image_identity, normalized, select_article, visible_text, visible_walk

ROOT = Path(__file__).resolve().parent
USAGE = '사용법: !공략 [임무번호] [해역(선택)]\n예: !공략 By10 / !공략 By10 55'
TERMS = {
    '高速+統一': '고속+통일', '高速統一': '고속통일', '低速統一': '저속통일',
    '高速': '고속', '低速': '저속', '最速': '최속',
    '巡洋艦': '순양함', '潜水空母': '잠수항모', '潜水艦': '잠수', '潜母': '잠수항모',
    '揚陸艦': '상륙함', '駆逐艦': '구축', '混合': '혼합', '港': '항구',
    '要索敵': '색적 필요', '索敵値': '색적', '式係数': '식 계수', '程度': '정도',
    '自由枠': '자유', '自由': '자유', '対地': '대지', '水雷戦隊': '수뢰전대',
    'ドラム缶': '드럼통', '輸送用': '수송용', '装備艦': '장비함',
    '秋津洲': '아키츠시마', '羽黒': '하구로', '足柄': '아시가라', '神風': '카미카제',
    'Gambier Bay Mk.II': '갬비어 베이 Mk.II', 'Gambier Bay': '갬비어 베이', 'Fletcher': '플레처 ',
    'ボス到達ランダム': '보스 도달 랜덤', 'ボス確定': '보스 도달 확정',
    'ルートランダム': '경로 랜덤', '道中ランダム': '도중 랜덤', 'ランダム': '랜덤',
    'ルート固定': '경로 고정', '固定不可': '고정 불가', '低確率で逸れあり': '낮은 확률로 이탈',
    'ランダムで逸れます': '랜덤으로 이탈', '経由することあり': '경유 가능',
    '初戦上の道中': '첫 분기 상단 / 도중', '道中': '도중', '戦固定': '전 고정',
    '後述': '후술', '何れも要索敵': '모두 색적 필요',
    '中央ルートで攻略可能です': '중앙 경로로 공략 가능',
    'のような編成にしたほうが攻略しやすいかも': '편성이 공략에 유리할 수 있음',
    'がいない場合や英米': '가 없거나 영미 ', 'が足りない場合': '이 부족한 경우',
    'がいない場合': '가 없는 경우',
    '航空戦艦': '항전', '航空巡洋艦': '항순', '重雷装巡洋艦': '뇌순',
    '正規空母': '정규항모', '装甲空母': '장갑항모', '軽空母': '경항모',
    '水上機母艦': '수모', '軽巡洋艦': '경순', '重巡洋艦': '중순',
    '補給艦': '보급', '補給': '보급', '旗艦': '기함',
    '渦潮': '와류', 'うずしお': '와류', '混成': '혼성',
    '正空': '정규항모', '軽空': '경항모',
    '夜戦空襲': '야간공습', '対潜空襲': '대잠공습',
    'レーダー射撃': '전탐사격', '電探射撃': '전탐사격', 'レーダー': '전탐', '電探': '전탐',
    '夜昼戦': '야간→주간전', '昼夜戦': '주간→야간전', '払暁戦': '새벽전',
    '空襲戦': '공습', '夜戦': '야전', '昼戦': '주간전', '空戦': '항공전',
    '能動分岐': '능동분기', '資源': '자원', '燃料': '연료', '弾薬': '탄약',
    '鋼材': '강재', 'ボーキサイト': '보키', 'ボーキ': '보키',
    '海防艦': '해방', '海防': '해방',
    '航空戦': '항공전', '空襲': '공습', '通常': '통상', '対潜': '대잠',
    '水雷': '수뢰', 'ボス': '보스', '戦艦': '전함', '軽巡': '경순',
    '重巡': '중순', '駆逐': '구축', '航巡': '항순', '航戦': '항전',
    '雷巡': '뇌순', '水母': '수모', '潜水': '잠수', '空母': '항모',
}
FLEET_TYPES = (
    r'(?:航空戦艦|航空巡洋艦|重雷装巡洋艦|正規空母|装甲空母|軽空母|水上機母艦|'
    r'軽巡洋艦|重巡洋艦|補給艦|海防艦|戦艦|軽巡|重巡|駆逐艦|駆逐|海防|'
    r'正空|軽空|空母|水母|航巡|航戦|潜水|潜母|雷巡|補給)'
)
NODE_ROUTE = r'【(?=[^】]*[A-Z])[A-Z0-9\s()→⇒←↔/・,.\-~?]+】'


def translate_route(text):
    text = unicodedata.normalize('NFKC', text)
    # Keep numeric constraints while removing redundant prose around a fleet.
    text = re.sub(r'が(\d+)隻以下', r' 합계 \1척 이하', text)
    text = re.sub(r'(\d+)隻以上', r'\1척 이상', text)
    text = re.sub(r'(\d+)隻以下', r'\1척 이하', text)
    text = re.sub(r'(\d+)隻に装備', r'\1척에 장착', text)
    text = re.sub(r'を(\d+)隻を採用', r'\1척', text)
    for phrase in ('のような編成で', 'の編成で', 'とすることで', 'を採用することで',
                   'という形にして', '以上の編成で', '以上の条件であれば'):
        replacement = '이상' if phrase.startswith('以上') else ''
        text = text.replace(phrase, replacement)
    text = text.replace('を入れなければ', ' 제외')
    text = text.replace('といった編成で', '')
    text = text.replace('で最短ルート', '(최단 경로)').replace('で下ルートの', '(하단 경로)')
    text = text.replace('隻以上で', '척 이상').replace('の水雷戦隊編成で', '')
    text = text.replace('の 水雷戦隊編成で', '')
    text = text.replace('に変更可能です。', '로 변경 가능. ')
    text = text.replace('に変更すること。', '로 변경. ')
    text = text.replace('を', ' ').replace('等', ' 등')
    for original in sorted(TERMS, key=len, reverse=True):
        text = text.replace(original, TERMS[original])
    text = re.sub(r'(아키츠시마|하구로|아시가라|카미카제)(?=[가-힣])', r'\1 ', text)
    text = re.sub(r'(?<=[가-힣])系', '계', text)
    text = re.sub(r'(?<=[가-힣])級', '급', text)
    text = re.sub(r'(?<=\d)系', '계', text)
    text = re.sub(r'(?<=[가-힣])艦', '함', text)
    text = text.replace('以上', ' 이상').replace('以下', ' 이하')
    text = re.sub(r'(\d+)戦の', r'\1전 / ', text)
    text = re.sub(r'(\d+)戦', r'\1전', text)
    text = re.sub(r'(?<=\d)で(?=\d)', ' / ', text)
    text = re.sub(r'(の編成で|のような編成で|編成で)', '', text)
    text = re.sub(r'で[、\s]*(?=【)', '', text)
    text = re.sub(r'の[、\s]*(?=【)', '', text)
    text = re.sub(r'も[、\s]*(?=【)', '', text)
    text = re.sub(r'[、。]\s*(?=【)', '', text)
    text = re.sub(
        r'(\d)(?=(?:정규항모|장갑항모|경항모|전함|항전|항순|중순|경순|뇌순|구축|해방|'
        r'잠수항모|잠수|수모|상륙함|보급|순양함|자유|아키츠시마|하구로|아시가라|카미카제))',
        r'\1 ', text,
    )
    text = re.sub(r'([A-Z])보스', r'\1:보스', text)
    text = re.sub(r'(?<!\s)【', ' 【', text)
    return text


def find_route(text):
    # Articles can place fleet counts and the route on separate HTML lines.
    # Capture only the route and battle types, not following quest notes.
    text = re.sub(r'\s+', ' ', text).strip()
    starter = (r'(?:' + FLEET_TYPES + r'(?:系|級)?(?=\s*(?:\d|[+(]|を\d))'
               r'|Gambier Bay(?: Mk\.II)?|Fletcher|秋津洲|羽黒|足柄|神風)')
    match = re.search(starter + r'[^。※]*?。?\s*' + NODE_ROUTE, text)
    if not match:
        return None
    end = match.end()
    annotation_start = end + len(text[end:]) - len(text[end:].lstrip())
    if annotation_start < len(text) and text[annotation_start] == '(':
        depth = 0
        for index in range(annotation_start, len(text)):
            if text[index] == '(':
                depth += 1
            elif text[index] == ')':
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
    return text[match.start():end]


def find_random_fleet(text):
    """A fleet-only lead paragraph is valid even without a fixed node route."""
    text = unicodedata.normalize('NFKC', text).strip()
    pattern = r'(' + FLEET_TYPES + r'(?:\([^)]*\))?\s*\d+\s*)+'
    match = re.match(r'^' + pattern, text)
    if not match and not text.startswith('Gambier Bay'):
        # Older articles embed a complete fleet in prose rather than using
        # a standalone lead line. Do not mistake a single suggested swap
        # (e.g. "自由枠に軽空母2採用") for a complete fleet.
        candidates = list(re.finditer(pattern, text.split('※')[0]))
        match = next((m for m in candidates if len(re.findall(FLEET_TYPES, m.group())) >= 2
                      and sum(map(int,re.findall(r'\d+',m.group()))) >= 4), None)
    if not match:
        named = re.match(r'Gambier Bay(?: Mk\.II)?(?:\(旗艦\))?Fletcher[^。※\n]+',text)
        if not named:
            return None
        fleet = translate_route(named.group())
    else:
        fleet = translate_route(match.group().strip())
    if 'ルートランダム' in text or '固定不可' in text or 'ランダムで逸れ' in text:
        note = '경로 랜덤'
        battle_count = re.search(r'道中\s*(\d+)戦', text)
        if battle_count:
            note += f' / 도중 {battle_count.group(1)}전'
        if 'ボス確定' in text:
            note += ' / 보스 도달 확정'
    elif 'ボス到達はランダム' in text:
        note = '보스 도달 랜덤'
    else:
        note = '고정 경로 표기 없음'
    return fleet + '\n' + note


def guide_map(value, maps=()):
    """Preserve explicit gauges; fill omitted gauges only when unambiguous."""
    value = unicodedata.normalize('NFKC', value).strip()
    value = quests.SORTIE_BOSS_MAPS.get(value, value)
    value = re.sub(r'^([1-7]-[1-6])-?[A-Z]$', r'\1', value)
    match = re.fullmatch(r'([1-7])-?([1-6])(?:-?(?:P)?([1-3]))?', value)
    if not match:
        return None
    area = '-'.join(part for part in match.groups() if part)
    if match[3]:
        return area
    candidates = {item for item in maps if item == area or item.startswith(area + '-')}
    return next(iter(candidates)) if len(candidates) == 1 else area


def sortie_maps(value):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'map':
                for item in child if isinstance(child, list) else [child]:
                    area = guide_map(item) if isinstance(item, str) else None
                    if area:
                        found.append(area)
            else:
                found.extend(sortie_maps(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(sortie_maps(child))
    return list(dict.fromkeys(found))


def map_fleet_sections(text):
    """Split shared fleet paragraphs with explicit per-map route notes."""
    labels = list(re.finditer(r'(?<![0-9])([1-7]-[1-6](?:-[1-3])?)\s*:', text))
    if not labels:
        return []
    fleet = text[:labels[0].start()].strip().rstrip('・● \r\n')
    if not re.match(r'^' + FLEET_TYPES + r'(?:\([^)]*\))?\s*\d', fleet):
        return []
    sections = []
    for index, label in enumerate(labels):
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        note = re.split(r'※|制空シミュ', text[label.end():end])[0].strip()
        route = find_route(fleet + ' ' + note)
        if route:
            summary = translate_route(route)
        else:
            count = re.search(r'道中\s*(\d+)戦', note)
            if not count and 'ランダム' not in note and '固定不可' not in note:
                continue
            summary = translate_route(fleet) + '\n'
            summary += f'도중 {count[1]}전' if count else '고정 경로 표기 없음'
            if 'ランダム' in note or '固定不可' in note:
                summary += ' / 경로 랜덤'
        sections.append((label[1], summary))
    return sections


def group_shared_fleets(entries):
    """Share fleet labels only when both the images and fleet text agree."""
    groups = []
    for heading, summary, images in entries:
        fleet, separator, route = summary.partition('\n')
        key = (tuple(images), fleet) if separator else None
        group = next((item for item in groups if key and item['key'] == key
                      and heading not in item['headings']), None)
        if group is None:
            groups.append({'key': key, 'fleet': fleet, 'headings': [heading],
                           'routes': [route], 'summary': summary})
        else:
            group['headings'].append(heading)
            group['routes'].append(route)
    rendered = []
    for group in groups:
        headings = group['headings']
        if len(headings) == 1:
            rendered.append(f'{headings[0]}: {group["summary"]}')
        else:
            rendered.append('/'.join(headings) + ': ' + group['fleet'] + '\n' +
                            '\n'.join(f'{area}: {route}' for area, route in
                                      zip(headings, group['routes'])))
    return rendered


def record_matches(record, quest):
    """A cache folder name alone is not proof of the quest's identity."""
    codes = {normalized(code) for code in [quest['wiki_id'], *quest.get('aliases', [])]}
    return (normalized(record.get('code', '')) in codes
            and normalized(record.get('name_jp', '')) == normalized(quest.get('name_jp', ''))
            and bool(quest.get('name_jp')))


def article_matches(html, record, quest):
    url = urlparse(record.get('url', ''))
    if url.scheme != 'https' or url.hostname != 'zekamashi.net' or not url.path.startswith('/kancolle-kouryaku/'):
        return False
    titles = [node.text() for node in Document(html).root.walk() if node.tag == 'h1']
    return any(normalized(quest['name_jp']) in normalized(title) for title in titles)


def build_preview(query, root=ROOT, *, cache_root=None, verify_images=True, diagnostics=None):
    """Return text and local fleet images; never fetch from the network."""
    args = query.strip().split()
    if len(args) >= 2 and re.fullmatch(r'\d{4}', args[0]) and re.fullmatch(r'[A-Za-z]+\d+', args[1]):
        args = [args[0] + args[1], *args[2:]]
    if len(args) not in (1, 2):
        return USAGE, []
    target_map = None
    if len(args) == 2:
        target_map = guide_map(args[1])
        if not target_map:
            return USAGE, []
    catalog = quests.catalog()
    key = catalog.by_code.get(args[0].casefold())
    if key is None:
        return f"'{args[0]}' 임무를 찾지 못했습니다.\n{USAGE}", []
    quest = catalog.items[key]
    code = quest['wiki_id']
    header = f"{code}: {quest['name_ko']}"
    folder = (Path(cache_root) if cache_root else Path(root) / 'guide_cache' / 'zekamashi') / re.sub(r'[^A-Za-z0-9_-]', '_', code)
    try:
        record = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return header + '\n\n아직 수집된 공략이 없습니다.', []
    if not record_matches(record, quest):
        return header + '\n\n저장된 공략의 임무 번호·제목을 확인 중입니다.', []
    if record.get('status') == 'no_match_on_first_page':
        return header + '\n\n등록된 공략이 없습니다.', []
    if record.get('status') != 'downloaded' or record.get('schema_version') != 2:
        return header + '\n\n공략 수집 중이거나 확인이 필요한 자료입니다.', []
    html = (folder / 'article.html').read_text(encoding='utf-8')
    if not article_matches(html, record, quest):
        return header + '\n\n저장된 공략의 원문 제목·출처를 확인 중입니다.', []
    if record.get('text_only'):
        return (header + '\n\n편성·경로 공략이 없는 연습/공창 임무입니다.\n'
                + f'임무 조건: !임무 {code}\n공략 원문: {record["url"]}'), []

    known = {}
    for image in record.get('images', []):
        path = (folder / image['file']).resolve()
        if path.parent != folder.resolve() or (verify_images and not path.is_file()):
            return header + '\n\n편성 이미지 수집이 아직 완료되지 않았습니다.', []
        known[image_identity(image['url'])] = path
    body = select_article(html)
    maps = sortie_maps(quest.get('requirements', {}))
    if target_map:
        target_map = guide_map(target_map, maps)
    current_map = maps[0] if len(maps) == 1 else None
    active, air = False, False
    variants = []
    phase = ''
    pending = []
    for node in visible_walk(body):
        if node.tag == 'h2':
            is_fleet = fleet_section_heading(visible_text(node))
            if active and not is_fleet:
                break
            active = is_fleet
            if active:
                air, phase, pending = False, '', []
                heading_map = re.search(r'(?<![0-9])[1-7]-[1-6](?:-[1-3])?(?![0-9])',
                                        unicodedata.normalize('NFKC',visible_text(node)))
                if heading_map:
                    current_map = guide_map(heading_map.group(), maps)
            continue
        if not active:
            continue
        text = unicodedata.normalize('NFKC', visible_text(node)).strip()
        if node.tag in {'h3', 'h4', 'h5', 'h6'}:
            match = re.search(r'(?<![0-9])[1-7]-[1-6](?:-[1-3])?(?![0-9])', text)
            if match:
                current_map, air = guide_map(match.group(), maps), False
                phase = ''
                pending = []
            if '基地航空隊' in text:
                air = True
        phase_label = node.tag in {'h3', 'h4', 'h5', 'h6'} or (
            node.tag == 'p' and re.match(r'^[●※\s]*ゲージ破壊(?:前|後)', text))
        if phase_label:
            before, after = 'ゲージ破壊前' in text, 'ゲージ破壊後' in text
            if before != after:
                phase = '게이지 파괴 전' if before else '게이지 파괴 후'
                air = False
                if node.tag != 'p':
                    pending = []
        if node.tag in {'a', 'img'}:
            url = (node.attrs.get('href', '') if node.tag == 'a'
                   else node.attrs.get('data-src') or node.attrs.get('src', ''))
            path = known.get(image_identity(url))
            if path and not air and path not in pending:
                pending.append(path)
        if node.tag == 'p' and not air:
            sections = map_fleet_sections(text)
            if sections and pending:
                for area, summary in sections:
                    variants.append({'map': guide_map(area, maps), 'phase': phase,
                                     'summary': summary, 'pictures': list(pending)})
                pending = []
                continue
            match = find_route(text)
            summary = translate_route(match) if match else find_random_fleet(text)
            if summary and current_map:
                if not pending:
                    continue
                variants.append({'map': current_map, 'phase': phase,
                                 'summary': summary, 'pictures': list(pending)})
                pending = []
    summaries, pictures, selected = [], [], set()
    observed = set(variant['map'] for variant in variants)
    def covers(expected, actual):
        return expected == actual or (expected.count('-') == 1 and actual.startswith(expected+'-'))
    unexpected = {area for area in observed if not any(covers(m,area) for m in maps)} if maps else set()
    missing = {area for area in maps if not any(covers(area,m) for m in observed)}
    if diagnostics is not None:
        diagnostics.update(expected_maps=maps, observed_maps=sorted(observed),
                           unexpected_maps=sorted(unexpected), missing_maps=sorted(missing))
    if unexpected:
        return header + '\n\n저장된 공략의 해역이 임무 조건과 달라 확인 중입니다.', []
    for variant in variants:
        area, label = variant['map'], variant['phase']
        if target_map and area != target_map:
            continue
        # The overview picks the first example per map. The detail picks
        # the first example per explicit gauge phase; unlabelled variants
        # remain separate rather than guessing whether they are pre/post.
        identity = (area, label) if target_map and label else (
            (area, len(summaries)) if target_map else area)
        if identity in selected:
            continue
        selected.add(identity)
        heading = f'{area} [{label}]' if target_map and label else area
        route_match = re.search(NODE_ROUTE, variant['summary'])
        if route_match:
            fleet = variant['summary'][:route_match.start()].strip()
            # Alternative fleet descriptions may themselves be bracketed.
            fleet = fleet.replace('】【', ' / ').replace('【', '').replace('】', '')
            summary = f'{fleet}\n{variant["summary"][route_match.start():]}'
        else:
            summary = variant['summary']
        summaries.append((heading, summary, variant['pictures']))
        for path in variant['pictures']:
            if path not in pictures:
                pictures.append(path)
    if not summaries or not pictures:
        return header + '\n\n저장된 공략의 편성·해역 연결을 확인 중입니다.', []
    result = header + '\n\n' + '\n\n'.join(group_shared_fleets(summaries))
    if missing and not target_map:
        result += '\n\n※ ' + '/'.join(sorted(missing)) + ' 공략 연결은 확인 중입니다.'
    return result, pictures
