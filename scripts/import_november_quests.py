"""Import only the three reviewed 2026-11-11 wiki rows and EO identities."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_new_quests import read_source, validate
from scripts.import_new_quests import rewards

EO_REVISION = '1b8d0b9e8f6cff3aee1f27dd7e920c2c2bb2a35d'
EO_SHA256 = '30c3a8e6a4154fe47c21723aba829648a7c2978ae757e8107c1b2861bfaeba15'
SPECS = {
    '2611 C1': ('2611 Cw1', 381, '【期間限定任務】秋月型演習任務2026', '【기간한정임무】아키즈키급 연습 임무 2026'),
    '2611 C2': ('2611 Cw2', 386, '【期間限定任務】秋刀魚祭り準備演習！', '【기간한정임무】꽁치 축제 준비 연습!'),
    'F144': ('2611 F1', 1172, '【雷装強化工廠任務】夜戦突撃装備の強化【I】', '【뇌장강화공창임무】야전 돌격 장비 강화 【I】'),
}
REWARD_NAMES = {
    '開発資材': '개발자재', '改修資材': '개수자재', '工廠資源': '공창자원',
    '高速修復材': '고속수복재', '25mm単装機銃': '25mm 단장기총',
    '三式水中探信儀': '3식 수중탐신의', '探照灯': '탐조등',
    '熟練見張員': '숙련견시원', '勲章': '훈장',
    '61cm四連装(酸素)魚雷後期型': '61cm 사연장(산소)어뢰 후기형',
    '61cm五連装(酸素)魚雷': '61cm 오연장(산소)어뢰',
}


def extract(html, eo_bytes, root=ROOT):
    if hashlib.sha256(eo_bytes).hexdigest() != EO_SHA256:
        raise ValueError('EO snapshot changed; review the source before importing')
    eo = {row['name_jp']: row for row in json.loads(eo_bytes)}
    soup = validate(html)
    review = json.loads((root / 'data/new_quest_november_review.json').read_text(encoding='utf-8'))
    rows = {}
    for tr in soup.select('tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) == 10:
            code = cells[0].get_text(' ', strip=True)
            if code in SPECS:
                if code in rows:
                    raise ValueError('Duplicate source row: ' + code)
                rows[code] = cells
    if set(rows) != set(SPECS):
        raise ValueError('Missing November quest rows')
    with (root / 'ships.csv').open(encoding='cp932', newline='') as stream:
        ships = [r for r in csv.DictReader(stream) if 0 < int(r['艦船ID']) < 1500]
    ids = {r['艦名']: int(r['艦船ID']) for r in ships}
    akizuki = [int(r['艦船ID']) for r in ships if r['艦型'] == '54']
    result = []
    for wiki, (code, api_id, jp, ko) in SPECS.items():
        cells = rows[wiki]
        raw = [c.get_text(' ', strip=True) for c in cells]
        digest = hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode()).hexdigest()
        if raw[1] != jp or digest != review[wiki]:
            raise ValueError('Wiki row changed; review before importing: ' + wiki)
        identity = eo[jp]
        if identity['code'] != code or identity['api_id'] != api_id:
            raise ValueError('EO quest identity changed: ' + wiki)
        req = {}
        if wiki == '2611 C1':
            pool = sorted(set(akizuki + [ids[n] for n in ('秋雲', '秋霜', '秋津洲')]))
            req = {'category': 'exercise', 'comp': [{'ship_id': pool, 'amount': 3}],
                   'result': 'A', 'times': 3, 'daily': True}
            lines = ['아키즈키급/아키구모/아키시모/아키츠시마 중 3 이상 + 자유 0~3',
                     '오늘 중 연습 A승 이상 3회']
            before = ['Cd1']
        elif wiki == '2611 C2':
            pool = [ids[n] for n in ('曙', '天霧', '村雨', '大潮', '熊野丸', '山汐丸', '第四号海防艦', 'Ranger', 'Heywood L.E.')]
            req = {'category': 'exercise', 'comp': [{'ship_id': pool, 'amount': 4},
                   {'ship_id': pool, 'position': 1, 'amount': 1}], 'result': 'S', 'times': 3, 'daily': True}
            lines = ['아케보노/아마기리/무라사메/오오시오/쿠마노마루/야마시오마루/제4호 해방함/Ranger/Heywood L.E. 중 4 이상(기함 포함) + 자유 0~2',
                     '오늘 중 연습 S승 3회']
            before = ['Bd5']
        else:
            req = {'category': 'equipexchange',
                   'slots': [{'id': 58, 'slot': 1}, {'id': 58, 'slot': 2}, {'id': 15, 'slot': 3, 'stars': 10}],
                   'scrap': [{'category': 'equipment', 'id': 14, 'amount': 10}],
                   'consume': [{'category': 'inventory', 'id': 3, 'amount': 60},
                               {'category': 'inventory', 'id': 94, 'amount': 2},
                               {'category': 'inventory', 'id': 104, 'amount': 2}]}
            lines = ['임무 수락 후 기함 1·2번 슬롯에 61cm 오연장(산소)어뢰 각 1개 장착(개수치 무관)',
                     '기함 3번 슬롯에 61cm 사연장(산소)어뢰 ★MAX 장착',
                     '폐기: 61cm 사연장어뢰 x10(산소어뢰가 아닌 일반 어뢰)',
                     '준비·소모: 개발자재 x60 / 신형병장자재 x2 / 공창자원 x2',
                     '주의: 장착한 사연장(산소)어뢰 ★MAX는 소멸하며, 오연장(산소)어뢰 2개는 ★MAX 장비로 교체됨']
            before = ['Fd5']
        weekly = wiki != 'F144'
        if weekly and ('ウィークリー' not in raw[8] or identity.get('progressResetType') != 1):
            raise ValueError('Exercise frequency needs review: ' + wiki)
        aliases = list(dict.fromkeys([code, code.replace(' ', ''), wiki, wiki.replace(' ', '')]))
        result.append({'wiki_id': code, 'source_wiki_id': wiki, 'game_api_id': api_id,
                       'name_jp': jp, 'name_ko': ko, 'aliases': aliases,
                       'category': 'exercise' if weekly else 'factory',
                       'frequency': 'weekly' if weekly else 'onetime', 'limited': weekly,
                       'release_date': '2026-11-11', 'unavailable': False,
                       'unverified': True, 'prereqs_unverified': True,
                       'prerequisite_incomplete': '()' in raw[8], 'prerequisite_codes': before,
                       'requirements': req, 'requirements_ko': lines, 'description': ' / '.join(lines),
                       'rewards': {'resources': [int(n) for n in raw[3:7]], 'other': rewards(cells[7], REWARD_NAMES)},
                       'source_row': raw, 'source_sha256': digest})
    return {'schema': 1, 'source': {
        'url': 'https://wikiwiki.jp/kancolle/任務/フロントページ#New',
        'html_sha256': hashlib.sha256(html.encode()).hexdigest(), 'reviewed_date': '2026-11-12',
        'code_reference': f'ElectronicObserverEN/Data@{EO_REVISION}:Data/Quests.json',
        'eo_sha256': EO_SHA256, 'code_policy': 'EO canonical codes and API IDs; reviewed wiki codes retained as aliases',
        'conditions_and_rewards': 'User-provided HAR response HTML; headers, cookies and other requests are not retained',
    }, 'quests': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wiki', type=Path, help='Reviewed HTML or HAR')
    parser.add_argument('eo', type=Path, help='Pinned EO Quests.json')
    args = parser.parse_args()
    result = extract(read_source(args.wiki), args.eo.read_bytes())
    (ROOT / 'data/quest_november_updates.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Imported three reviewed November quests')
