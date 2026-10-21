"""Preview composition summaries from locally collected Zekamashi guides."""
import json
import re
import unicodedata
from pathlib import Path

import quests
from scripts.collect_zekamashi import image_identity, normalized, select_article, visible_text, visible_walk

ROOT = Path(__file__).resolve().parent
USAGE = '사용법: !공략 [임무번호]\n예: !공략 B44 / !공략 By10'
TERMS = {
    '航空戦艦': '항전', '航空巡洋艦': '항순', '重雷装巡洋艦': '뇌순',
    '正規空母': '정규항모', '装甲空母': '장갑항모', '軽空母': '경항모',
    '水上機母艦': '수모', '軽巡洋艦': '경순', '重巡洋艦': '중순',
    '補給艦': '보급', '補給': '보급', '旗艦': '기함',
    '渦潮': '와류', 'うずしお': '와류', '混成': '혼성',
    '正空': '정규항모', '軽空': '경항모',
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
    if len(args) != 1:
        return USAGE, []
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
    summaries, pictures = [], []
    selected_maps = set()
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
        if node.tag in {'h3', 'h4'}:
            match = re.search(r'[1-7]-[1-6]', text)
            if match:
                current_map, air = match.group(), False
                pending = []
            if '基地航空隊' in text:
                air = True
        if node.tag in {'a', 'img'}:
            url = (node.attrs.get('href', '') if node.tag == 'a'
                   else node.attrs.get('data-src') or node.attrs.get('src', ''))
            path = known.get(image_identity(url))
            if path and not air and path not in pending:
                pending.append(path)
        if node.tag == 'p' and not air:
            match = re.search(r'(?:戦艦|軽巡|重巡|駆逐|正空|軽空|空母|水母|航巡|航戦|潜水|雷巡|補給).*?【[^】]+】[^\n]*', text)
            if match and current_map:
                if current_map in selected_maps or not pending:
                    pending = []
                    continue
                summary = f'{current_map}: {translate_route(match.group())}'
                summaries.append(summary)
                selected_maps.add(current_map)
                for path in pending:
                    if path not in pictures:
                        pictures.append(path)
                pending = []
    if not summaries or not pictures:
        return header + '\n\n저장된 공략의 편성·해역 연결을 확인 중입니다.', []
    return header + '\n\n' + '\n'.join(summaries), pictures
