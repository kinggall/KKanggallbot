"""Import the reviewed 2026-10-14 wiki snapshot; fail closed on changed rows."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_new_quests import read_source

# Reviewed titles, exact candidate pools, required counts and flagship rules.
SPECS = {
 '2610 B1': ('【期間限定任務】14年目実りの秋、南瓜始め！', '【기간한정임무】14년째 결실의 가을, 호박 시작!', '鈴谷/村雨/夕立/曙/朧/朝潮/野分/迅鯨/長鯨', 3, True),
 '2610 B2': ('【期間限定任務】特務護衛戦隊、抜錨せよ！', '【기간한정임무】특무호위전대, 발묘하라!', '対馬/鵜来/稲木/大泊/迅鯨/長鯨/朝日/村雨/巻波/早波/浜波/樫', 3, False),
 '2610 B3': ('【期間限定任務】USS Trick or Treat！', '【기간한정임무】USS Trick or Treat!', 'Minneapolis/Tuscaloosa/Gambier Bay/Brooklyn/Johnston/Richard P.Leary/Indiana', 3, False),
 '2610 B4': ('【期間限定任務】西方南瓜祭り! Buono!', '【기간한정임무】서방 호박 축제! Buono!', 'Roma/Luigi Torelli/Maestrale/Grecale/Libeccio/Scirocco/Jervis/伊47/伊201/鈴谷/村雨/朧/曙', 3, True),
 '2610 B5': ('【限定拡張作戦】Halloween、おかわり開始！', '【한정확장작전】Halloween, 추가 시작!', '鈴谷/曙/朧/樫/朝日/迅鯨/長鯨/瑞穂/Johnston/Richard P.Leary', 4, True),
 '2610 B6': ('【限定拡張作戦】Halloween海上護衛隊出撃！', '【한정확장작전】Halloween 해상호위대 출격!', '対馬/樫/朝潮/巻波/浜波/阿武隈/鵜来/稲木/能美/第四号海防艦/第二十二号海防艦/第三〇号海防艦', 4, False),
 '2610 B7': ('【限定拡張作戦】Halloween狼隊、夜の襲撃！', '【한정확장작전】Halloween 늑대대, 밤의 습격!', '朧/夕立/野分/早波/熊野丸/迅鯨改/Tuscaloosa/Indiana', 3, True),
 '2610 B8': ('【限定拡張作戦】南瓜祭り2026、北方作戦！', '【한정확장작전】호박 축제 2026, 북방작전!', 'Minneapolis/Tuscaloosa/Gambier Bay/Johnston/鈴谷/阿武隈/曙/朧/清霜/樫', 3, True),
 '2610 C1': ('Halloween艦隊 実りの秋、最新演習！', 'Halloween 함대, 결실의 가을 최신 연습!', '鈴谷/阿武隈/朧/曙/村雨/夕立/野分/朝潮/早波/浜波/伊201/Jervis/Minneapolis/Johnston', 4, False),
 '2610 F1': ('【期間限定】Halloweenの南瓜、食べりゅ?', '【기간한정】Halloween의 호박, 먹을래?', '', 0, False),
 '2610 F2': ('【限定拡張作戦】対潜装備の整理整頓！2026', '【한정확장작전】대잠장비 정리정돈! 2026', '', 0, False),
 'B218': ('再編二十駆「天霧」「狭霧」南方へ展開せよ！', '재편 제20구축대 「아마기리」「사기리」 남방으로 전개하라!', '天霧改二/天霧改二丁/狭霧改二', 2, False),
}

NAMES = {
 '鈴谷':'스즈야','村雨':'무라사메','夕立':'유다치','曙':'아케보노','朧':'오보로','朝潮':'아사시오','野分':'노와키',
 '迅鯨':'진게이','迅鯨改':'진게이 개1','長鯨':'쵸게이','対馬':'쓰시마','鵜来':'우쿠루','稲木':'이나기','大泊':'오오토마리',
 '朝日':'아사히','巻波':'마키나미','早波':'하야나미','浜波':'하마나미','樫':'카시','Minneapolis':'미니애폴리스',
 'Tuscaloosa':'터스컬루사','Gambier Bay':'갬비어 베이','Brooklyn':'브루클린','Johnston':'존스턴','Richard P.Leary':'리처드 P. 리어리',
 'Indiana':'인디애나','Roma':'로마','Luigi Torelli':'루이지 토렐리','Maestrale':'마에스트랄레','Grecale':'그레칼레',
 'Libeccio':'리베치오','Scirocco':'시로코','Jervis':'저비스','伊47':'이47','伊201':'이201','瑞穂':'미즈호','阿武隈':'아부쿠마',
 '能美':'노미','第四号海防艦':'제4호 해방함','第二十二号海防艦':'제22호 해방함','第三〇号海防艦':'제30호 해방함',
 '熊野丸':'쿠마노마루','清霜':'키요시모','天霧改二':'아마기리 개2','天霧改二丁':'아마기리 개2정','狭霧改二':'사기리 개2',
}
REWARD_NAMES = {
 '開発資材':'개발자재','高速修復材':'고속수복재','勲章':'훈장','南瓜':'호박',
 '給糧艦「間宮」':'마미야','新型航空兵装資材':'신형항공병장자재','SKレーダー':'SK 레이더',
 '改装設計図':'설계도','海外艦最新技術':'해외함 최신기술','Ro.44水上戦闘機':'Ro.44 수상전투기',
 '工廠資源':'공창자원','改修資材':'개수자재','試製秋水':'시제 슈스이','戦闘詳報':'전투상보',
 '高速建造材':'고속건조재','燃料':'연료','ボーキサイト':'보키','三式水中探信儀':'3식 수중탐신의',
 'Type124ASDIC':'Type124 ASDIC','新型兵装資材':'신형병장자재','12.7cm連装砲B型改二':'12.7cm 연장포 B형 개2',
}


def rewards(cell):
    # Split on semantic list bullets, not DOM text boundaries inside item links.
    text = cell.get_text('', strip=True)
    chunks = re.split(r'(選択報酬[12]?|確定報酬)', text)
    output = []
    for i in range(1, len(chunks), 2):
        items = []
        for raw in chunks[i+1].split('・'):
            if not raw.strip():
                continue
            value = re.sub(r'\s+', '', raw)
            if value.startswith('装備運用枠'):
                amount = int(re.search(r'\+(\d+)装備分', value)[1])
                items.append({'category':'named', 'name':'장비 운용 슬롯', 'amount':amount})
                continue
            match = re.fullmatch(r'(.+?)(?:★\+?(\d+|max))?x(\d+)', value)
            if not match or match[1] not in REWARD_NAMES:
                raise ValueError('Unreviewed reward: ' + raw)
            item = {'category':'named', 'name':REWARD_NAMES[match[1]], 'amount':int(match[3])}
            if match[2]:
                item['stars'] = 10 if match[2]=='max' else int(match[2])
            items.append(item)
        output.extend([{'choices':items}] if chunks[i].startswith('選択') else items)
    if not output:
        raise ValueError('Missing rewards')
    return output


def extract(html, root=ROOT):
    soup = BeautifulSoup(html, 'html.parser')
    rows = {}
    for tr in soup.find_all('tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 10:
            continue
        raw = re.sub(r'\s+', '', cells[0].get_text())
        code = re.sub(r'^(2610)([BCF])', r'\1 \2', raw)
        if code not in SPECS:
            continue
        if code in rows:
            raise ValueError('Duplicate wiki row: ' + code)
        rows[code] = cells
    if set(rows) != set(SPECS):
        raise ValueError('Missing targets: ' + str(set(SPECS)-set(rows)))
    # Only reviewed conditions may be imported. A later maintenance snapshot
    # must be reviewed and explicitly added, never blindly machine-translated.
    expected = json.loads((root/'data/new_quest_review.json').read_text(encoding='utf-8'))
    ship_ids = {}
    with (root/'ships.csv').open(encoding='cp932', newline='') as stream:
        reader = csv.reader(stream)
        for row in reader:
            if row and row[0].isdigit():
                ship_ids[row[4]] = int(row[0])
    result = []
    for code, (title, ko, pool, count, flagship) in SPECS.items():
        cells = rows[code]
        raw = [c.get_text(' ',strip=True) for c in cells]
        digest = hashlib.sha256(json.dumps(raw,ensure_ascii=False).encode()).hexdigest()
        if digest != expected[code]:
            raise ValueError('Wiki row changed; review before importing: ' + code)
        if raw[1] != title:
            raise ValueError('Title mismatch: ' + code)
        category = 'exercise' if ' C' in code else 'factory' if ' F' in code else 'sortie'
        req = {'category': 'exercise' if category=='exercise' else 'sortie' if category=='sortie' else 'equipexchange'}
        lines = []
        names = pool.split('/') if pool else []
        if names:
            req['comp'] = [{'ship_id':[ship_ids[n] for n in names], 'amount':count}]
            if code=='B218':
                lines.append('아마기리 개2/개2정 중 1 + 사기리 개2 + 자유 0~4')
                req['comp'] = [{'ship_id':[ship_ids['天霧改二'],ship_ids['天霧改二丁']], 'amount':1},
                               {'ship_id':ship_ids['狭霧改二'], 'amount':1}]
            else:
                lines.append('/'.join(NAMES[n] for n in names) + f' 중 {count} 이상' +
                             ('(기함 포함)' if flagship else '') + f' + 자유 0~{6-count}')
        if category=='sortie':
            maps = re.findall(r'・\(([1-7]-[1-6](?:-[1-3])?)(?:/Z)?\)', raw[2])
            times = re.search(r'各(\d+)回\s*S勝利', raw[2])
            if not maps or not times:
                raise ValueError('Unknown sortie conditions: '+code)
            req['sortie'] = [{'map':maps,'boss':True,'result':'S','times':int(times[1])}]
            lines.append('/'.join(maps)+f' 보스 S승 각 {times[1]}회')
        elif category=='exercise':
            req.update(result='A',times=5,daily=True)
            lines.append('오늘 중 연습 A승 이상 5회')
        elif code=='2610 F1':
            lines = ['폐기: 소구경주포/중구경포/수상정찰기 각 9개',
                     '준비·소모: 99식 함폭 x10 / 97식 함공 x10 / 가구코인 x1031']
        else:
            lines = ['폐기: 94식 폭뢰투사기 x12 / 95식 폭뢰 x8 / 93식 수중청음기 x6',
                     '준비·소모: 호박 x2 / 3식 폭뢰투사기 x5 / 개발자재 x30']
        frequency = 'weekly' if 'ウィークリー' in raw[8] else 'monthly' if 'マンスリー' in raw[8] else 'onetime'
        prereqs = re.findall(r'\((2610[BCF]\d+|Bd5)\)',raw[8])
        prereqs = [re.sub(r'^(2610)([BCF])',r'\1 \2',p) for p in prereqs]
        result.append({'wiki_id':code,'name_jp':title,'name_ko':ko,'category':category,
                       'frequency':frequency,'limited':code.startswith('2610'), 'release_date':'2026-10-14',
                       'unavailable':False,'unverified':True,'prereqs_unverified':True,
                       'prerequisite_codes':prereqs,'requirements':req,'requirements_ko':lines,
                       'rewards':{'resources':[int(v) for v in raw[3:7]],'other':rewards(cells[7])},
                       'description':' / '.join(lines), 'source_row':raw,'source_sha256':digest,
                       'prerequisite_incomplete':'()' in raw[8]})
    return {'schema':1,'source':{'url':'https://wikiwiki.jp/kancolle/任務/フロントページ#New',
            'html_sha256':hashlib.sha256(html.encode()).hexdigest(),'reviewed_date':'2026-10-22',
            'identity_policy':'wiki: keys are local identities, NOT invented game API IDs'},'quests':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    args=parser.parse_args()
    result=extract(read_source(args.input))
    output=ROOT/'data/quest_wiki_updates.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Imported {len(result["quests"])} reviewed quests: {output}')


if __name__=='__main__':
    main()
