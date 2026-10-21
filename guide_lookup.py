"""Preview composition summaries from locally collected Zekamashi guides."""
import json
import re
import unicodedata
from pathlib import Path

import quests
from scripts.collect_zekamashi import image_identity, normalized, select_article, visible_text, visible_walk

ROOT = Path(__file__).resolve().parent
USAGE = '사용법: !공략 [임무번호] [해역(선택)]\n예: !공략 By10 / !공략 By10 55'
TERMS = {
    '航空戦艦': '항전', '航空巡洋艦': '항순', '重雷装巡洋艦': '뇌순',
    '正規空母': '정규항모', '装甲空母': '장갑항모', '軽空母': '경항모',
    '水上機母艦': '수모', '軽巡洋艦': '경순', '重巡洋艦': '중순',
    '補給艦': '보급', '補給': '보급', '旗艦': '기함',
    '渦潮': '와류', 'うずしお': '와류', '混成': '혼성',
    '正空': '정규항모', '軽空': '경항모',
    '夜戦空襲': '야간공습', '対潜空襲': '대잠공습',
    'レーダー射撃': '전탐', '電探射撃': '전탐', 'レーダー': '전탐', '電探': '전탐',
    '夜昼戦': '야간→주간전', '昼夜戦': '주간→야간전', '払暁戦': '새벽전',
    '空襲戦': '공습', '夜戦': '야전', '昼戦': '주간전', '空戦': '항공전',
    '能動分岐': '능동분기', '資源': '자원', '燃料': '연료', '弾薬': '탄약',
    '鋼材': '강재', 'ボーキサイト': '보키', 'ボーキ': '보키',
    '航空戦': '항공전', '空襲': '공습', '通常': '통상', '対潜': '대잠',
    '水雷': '수뢰', 'ボス': '보스', '戦艦': '전함', '軽巡': '경순',
    '重巡': '중순', '駆逐': '구축', '航巡': '항순', '航戦': '항전',
    '雷巡': '뇌순', '水母': '수모', '潜水': '잠수', '空母': '항모',
}


def translate_route(text):
    text = unicodedata.normalize('NFKC', text)
    for original in sorted(TERMS, key=len, reverse=True):
        text = text.replace(original, TERMS[original])
    text = re.sub(r'(\d)(?=[가-힣])', r'\1 ', text)
    text = re.sub(r'([A-Z])보스', r'\1:보스', text)
    text = re.sub(r'(?<!\s)【', ' 【', text)
    return text


def find_route(text):
    # Articles can place fleet counts and the route on separate HTML lines.
    # Capture only the route and battle types, not following quest notes.
    text = re.sub(r'\s+', ' ', text).strip()
    match = re.search(
        r'(?:戦艦|軽巡|重巡|駆逐|正空|軽空|空母|水母|航巡|航戦|潜水|雷巡|補給)'
        r'.*?【[^】]+】', text,
    )
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


def sortie_maps(value):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'map' and isinstance(child, str):
                match = re.search(r'[1-7]-[1-6]', child)
                if match:
                    found.append(match.group())
            else:
                found.extend(sortie_maps(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(sortie_maps(child))
    return list(dict.fromkeys(found))


def build_preview(query, root=ROOT):
    """Return text and local fleet images; never fetch from the network."""
    args = query.strip().split()
    if len(args) not in (1, 2):
        return USAGE, []
    target_map = None
    if len(args) == 2:
        match = re.fullmatch(r'([1-7])-?([1-6])', args[1])
        if not match:
            return USAGE, []
        target_map = '-'.join(match.groups())
    catalog = quests.catalog()
    key = catalog.by_code.get(args[0].casefold())
    if key is None:
        return f"'{args[0]}' 임무를 찾지 못했습니다.\n{USAGE}", []
    quest = catalog.items[key]
    code = quest['wiki_id']
    header = f"{code}: {quest['name_ko']}"
    folder = Path(root) / 'guide_cache' / 'zekamashi' / re.sub(r'[^A-Za-z0-9_-]', '_', code)
    try:
        record = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return header + '\n\n아직 수집된 공략이 없습니다.', []
    if record.get('status') == 'no_match_on_first_page':
        return header + '\n\n등록된 공략이 없습니다.', []
    if record.get('status') != 'downloaded' or record.get('schema_version') != 2:
        return header + '\n\n공략 수집 중이거나 확인이 필요한 자료입니다.', []

    known = {}
    for image in record.get('images', []):
        path = (folder / image['file']).resolve()
        if path.parent != folder.resolve() or not path.is_file():
            return header + '\n\n편성 이미지 수집이 아직 완료되지 않았습니다.', []
        known[image_identity(image['url'])] = path
    body = select_article((folder / 'article.html').read_text(encoding='utf-8'))
    maps = sortie_maps(quest.get('requirements', {}))
    current_map = maps[0] if len(maps) == 1 else None
    active, air = False, False
    variants = []
    phase = ''
    pending = []
    for node in visible_walk(body):
        if node.tag == 'h2':
            if active:
                break
            active = normalized(visible_text(node)) == normalized('編成例')
            continue
        if not active:
            continue
        text = unicodedata.normalize('NFKC', visible_text(node)).strip()
        if node.tag in {'h3', 'h4', 'h5', 'h6'}:
            match = re.search(r'[1-7]-[1-6]', text)
            if match:
                current_map, air = match.group(), False
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
            match = find_route(text)
            if match and current_map:
                if not pending:
                    continue
                variants.append({'map': current_map, 'phase': phase,
                                 'summary': translate_route(match), 'pictures': list(pending)})
                pending = []
    summaries, pictures, selected = [], [], set()
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
        fleet, separator, route = variant['summary'].partition('【')
        summary = f'{heading}: {fleet.rstrip()}'
        if separator:
            summary += '\n【' + route
        summaries.append(summary)
        for path in variant['pictures']:
            if path not in pictures:
                pictures.append(path)
    if not summaries or not pictures:
        return header + '\n\n저장된 공략의 편성·해역 연결을 확인 중입니다.', []
    return header + '\n\n' + '\n\n'.join(summaries), pictures
