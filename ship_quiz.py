"""Offline ship-family quiz with transactional, room-local persistent state."""
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from itertools import combinations
import csv
import json
import math
from pathlib import Path
import random
import sqlite3

from equipment_lookup import normalize
from initial_equipment import InitialEquipmentCatalog

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))  # Windows does not require a tzdata install.
NATIONS = {1: '일본', 2: '독일', 3: '이탈리아', 4: '미국', 5: '영국',
           6: '프랑스', 7: '소련', 8: '심해', 9: '호주', 10: '스웨덴', 11: '네덜란드'}
STATS = [('火力最大', '화력'), ('雷装最大', '뇌장'), ('対空最大', '대공'),
         ('装甲最大', '장갑')]
COMMANDS = {'!퀴즈', '!정답', '!퀴즈점수'}
QUIZ_TYPES = {
    1: '해방', 2: '구축',
    3: '경순', 4: '경순', 21: '경순',
    5: '중순', 6: '중순',
    7: '항모', 11: '항모', 18: '항모',
    8: '전함', 9: '전함', 10: '전함', 12: '전함',
    13: '잠수', 14: '잠수',
}


def quiz_type(ship_type):
    return QUIZ_TYPES.get(ship_type, '기타함종')


def quota_period(now):
    shifted = now.astimezone(KST) - timedelta(hours=3)
    return f"{shifted.date().isoformat()}:{'03' if shifted.hour < 12 else '15'}"


def quota_limit(now):
    local = now.astimezone(KST)
    if quota_period(local).endswith(':03'):
        return 10
    hour = local.hour if local.hour >= 15 else local.hour + 24
    return 10 + 5 * max(0, min(hour, 24) - 17)


def stage_label(row):
    stage = int(row['改装段階'])
    return '미개장' if stage == 0 else '개1' if stage == 1 else '개2 이상'


def initials(name):
    return ''.join('ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'[(ord(c)-0xAC00)//588]
                   if '가' <= c <= '힣' else c for c in name)


class QuizCatalog:
    def __init__(self, root=ROOT):
        meta = json.loads((root/'data/fit_metadata.json').read_text())['ships']
        labels = json.loads((root/'data/quests.json').read_text())['labels']['ships']
        aliases = json.loads((root/'data/ship_aliases.json').read_text())
        classes = json.loads((root/'data/quiz_ship_classes.json').read_text())['classes']
        self.answers = defaultdict(set)
        self.names = {}
        with (root/'ships.csv').open(encoding='cp932', newline='') as stream:
            ships = {int(r['艦船ID']): r for r in csv.DictReader(stream) if r['艦船ID'] in meta}
        translations = {}
        path = root/'data/ship-ko.json'
        if path.exists():
            translations.update(json.loads(path.read_text(encoding='utf-8-sig')).get('ship', {}))
        translations.update(json.loads((root/'data/ship_name_overrides.json').read_text()))
        from development import translated_ship_name
        for sid, row in ships.items():
            base = meta[str(sid)]['base']
            jp = row['艦名']
            name = labels.get(str(sid), translated_ship_name(jp, translations))
            self.names[sid] = name
            for answer in [jp, name, *aliases.get(jp, [])]:
                self.answers[normalize(answer)].add(base)
                if name.endswith('개') and answer == name:
                    self.answers[normalize(name+'1')].add(base)
        helper_items = defaultdict(set)
        upgrades = json.loads((root/'data/equipment_upgrades.json').read_text(encoding='utf-8-sig'))
        for row in upgrades:
            for route in row['improvement']:
                for helper in route['helpers']:
                    if helper['days']:
                        for sid in helper['ship_ids']:
                            helper_items[sid].add(row['eq_id'])
        equipment = InitialEquipmentCatalog(root)
        fingerprints = defaultdict(set)
        for sid, row in ships.items():
            info = meta[str(sid)]
            try:
                stats = {label:int(row[field]) for field,label in STATS if int(row[field]) > 0}
                common = (quiz_type(info['type']), NATIONS.get(info['nationality']),
                          stage_label(row), int(row['運初期']))
            except ValueError:
                continue
            for a,b in combinations(stats, 2):
                fingerprints[(*common, a, stats[a], b, stats[b])].add(info['base'])
        candidates = []
        for sid, row in ships.items():
            info = meta[str(sid)]
            if not helper_items[sid] or info['nationality'] not in NATIONS or info['nationality'] == 8:
                continue
            entries = equipment.starting_items(row)
            if not entries or None in entries:
                continue
            base_name = self.names.get(info['base'], '')
            if not any('가' <= c <= '힣' for c in base_name):
                continue
            try:
                stats = {label: int(row[field]) for field, label in STATS if int(row[field]) > 0}
                luck = int(row['運初期'])
                stage = stage_label(row)
                slots = [int(row[f'搭載機数{i}']) for i in range(1,int(row['スロット数'])+1)]
            except ValueError:
                continue
            ship_class = classes.get(str(info['ship_class']))
            if info['type'] in (1,2) and not ship_class:
                continue  # Never invent a class hint for an unmapped new class.
            candidates.append(dict(sid=sid, family=info['base'], name=self.names[sid],
                base_name=base_name, nation=NATIONS[info['nationality']],
                kind=quiz_type(info['type']), stage=stage, stats=stats, luck=luck,
                class_hint=ship_class if info['type'] in (1,2) else None, slots=slots,
                equipment=[equipment.equipment.items[i]['name'] + (f' ★{s}' if s else '') for i, s in entries],
                helpers=[equipment.equipment.items[i]['name'] for i in sorted(helper_items[sid])]))
        # Two stats + luck + type/nation/stage must identify one family among ALL
        # known CSV forms, including ships not eligible for hint-based selection.
        self.questions = []
        self.details = {q['sid']:q for q in candidates}
        for q in candidates:
            for pair in combinations(q['stats'], 2):
                a,b = pair
                other_families = fingerprints[(q['kind'], q['nation'], q['stage'], q['luck'],
                                               a, q['stats'][a], b, q['stats'][b])]
                if other_families == {q['family']}:
                    self.questions.append({**q, 'stats': {label:q['stats'][label] for label in pair}})
        if not self.questions:
            raise ValueError('No unambiguous ship quiz questions')

    def choose(self, recent):
        pool = [q for q in self.questions if q['family'] not in recent] or self.questions
        families = sorted({q['family'] for q in pool})
        family = random.choice(families)
        return dict(random.choice([q for q in pool if q['family'] == family]))


def render(active):
    q = active['question']
    lines = [f"[칸무스 퀴즈 · {active['number']}/{active.get('limit',10)}]", '',
             f"· 함종: {q['kind']} / 국적: {q['nation']}",
             f"· ({q['stage']}) " + ' / '.join(f'{k}: {v}' for k,v in q['stats'].items()),
             f"· 운: {q['luck']} (Lv 99 기준)"]
    wrong = active['wrong']
    if wrong >= 3:
        lines += ['', '💡 초기 장비: ' + ' / '.join(q['equipment'])]
    if wrong >= 5:
        lines += ['💡 개수 2번함 담당: ' + ' / '.join(q['helpers'][:3])]
    if wrong >= 7:
        if q.get('class_hint'):
            lines += ['💡 함급: ' + q['class_hint']]
        elif 'slots' in q:
            slots = q['slots']
            lines += ['💡 함재기 슬롯: ' + (' / '.join(map(str, slots)) if slots else '없음') +
                      (f' (총 {sum(slots)}기)' if slots else '')]
    if wrong >= 10:
        lines += ['💡 초성: ' + initials(q['base_name'])]
    lines += ['', f'누적 오답: {wrong}회']
    return '\n'.join(lines)


class QuizService:
    def __init__(self, catalog, database, now=None):
        self.catalog, self.database = catalog, Path(database)
        self.now = now or (lambda: datetime.now(KST))
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS rooms (room TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scores (room TEXT, player TEXT, name TEXT, points INTEGER, PRIMARY KEY(room,player))')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (room TEXT, player TEXT, submitted REAL, PRIMARY KEY(room,player))')

    def handle(self, message, room, player='', name=''):
        command, _, argument = message.strip().partition(' ')
        if command not in COMMANDS:
            return None
        if room is None or not str(room).strip():
            return '채팅방 정보를 확인할 수 없습니다.'
        room = str(room)
        with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE room=?', (room,)).fetchone()
            state = json.loads(row[0]) if row else {'day':'', 'count':0, 'active':None, 'recent':[]}
            now = self.now().astimezone(KST)
            period = quota_period(now)
            if state['active']:
                state['active'].setdefault('quota_period', state.get('period',period))
                state['active'].setdefault('limit',max(10,state['active']['number']))
            if 'period' not in state:
                # Preserve today's existing quota during deployment migration.
                if state.get('day') not in {now.date().isoformat(), period[:10]}:
                    state['count'] = 0
                state['period'] = period
            elif state['period'] != period:
                state['period'], state['count'] = period, 0
            state['day'] = now.date().isoformat()
            if state['active']:
                if state['active']['quota_period'] == period:
                    state['active']['limit'] = quota_limit(now)
                question = state['active']['question']
                detail = getattr(self.catalog,'details',{}).get(question['sid'])
                if detail:
                    for field in ('class_hint','slots'):
                        question.setdefault(field,detail[field])
            # 03:00/15:00 reset only quota, never an active question or scores.
            display_name = ' '.join(str(name or '').split())[:100]
            if display_name == '참가자':
                display_name = ''
            if player and display_name:
                db.execute('UPDATE scores SET name=? WHERE room=? AND player=?', (display_name,room,str(player)))
            if not display_name:
                saved = db.execute('SELECT name FROM scores WHERE room=? AND player=?', (room,str(player or ''))).fetchone()
                display_name = saved[0] if saved else '참가자'
            reply = self.dispatch(db, command, argument.strip(), room, str(player or ''), display_name, state)
            db.execute('INSERT INTO rooms VALUES (?,?) ON CONFLICT(room) DO UPDATE SET state=excluded.state',
                       (room, json.dumps(state, ensure_ascii=False)))
            return reply

    def dispatch(self, db, command, answer, room, player, name, state):
        active = state['active']
        if command == '!퀴즈점수':
            rows = db.execute('SELECT name,points FROM scores WHERE room=? ORDER BY points DESC,name,player LIMIT 20', (room,)).fetchall()
            return '[칸무스 퀴즈 순위]\n\n' + ('\n'.join(f'{i}. {n} · {p}점' for i,(n,p) in enumerate(rows,1)) or '아직 정답자가 없습니다.')
        if command == '!퀴즈':
            if active:
                return render(active)
            limit = quota_limit(self.now())
            if state['count'] >= limit:
                return (f'✔️ 퀴즈 {limit}회를 모두 사용했습니다.\n✔️ 연습전 시간에 초기화됩니다.\n'
                        '✔️ 핫타임(18~24) 정각에 5회씩 추가됩니다.')
            question = self.catalog.choose(state['recent'])
            state['count'] += 1
            state['recent'] = [*state['recent'], question['family']][-30:]
            state['active'] = dict(question=question, number=state['count'], wrong=0, seen=[],
                                   limit=limit, quota_period=state['period'])
            return render(state['active'])
        if not active:
            return '✔️ 진행 중인 문제가 없습니다.\n✔️ !퀴즈로 시작해 주세요.'
        q = active['question']
        if not answer or not normalize(answer):
            return '사용법: !정답 [함선명/별명]'
        if not player:
            return '참가자 정보를 확인할 수 없어 정답을 처리하지 못했습니다.'
        if len(answer) > 100:
            return '함선명 또는 등록된 별명을 100자 이내로 입력해 주세요.'
        timestamp = self.now().timestamp()
        last = db.execute('SELECT submitted FROM attempts WHERE room=? AND player=?',(room,player)).fetchone()
        if last and timestamp-last[0] < 60:
            remaining = min(60,math.ceil(60-(timestamp-last[0])))
            return f'✔️ 정답은 1분에 한 번 제출할 수 있습니다.\n✔️ {remaining}초 후 다시 시도해 주세요.'
        key = normalize(answer)
        families = self.catalog.answers.get(key, set())
        if len(families) > 1:
            return '여러 함선에 해당하는 이름입니다. 정확한 함선명으로 답해 주세요.'
        attempt = [player, key[:200]]
        if attempt in active['seen']:
            return '✔️ 이미 제출한 오답입니다.\n✔️ 오답 횟수는 늘어나지 않습니다.'
        db.execute('INSERT INTO attempts VALUES (?,?,?) ON CONFLICT(room,player) DO UPDATE SET submitted=excluded.submitted',
                   (room,player,timestamp))
        if q['family'] in families:
            db.execute('INSERT INTO scores VALUES (?,?,?,1) ON CONFLICT(room,player) DO UPDATE SET points=points+1,name=excluded.name', (room,player,name[:100]))
            points = db.execute('SELECT points FROM scores WHERE room=? AND player=?', (room,player)).fetchone()[0]
            state['active'] = None
            return f"🎉 {name[:100]}님 정답!\n정답: {q['name']}\n\n+1점 · 누적 {points}점\n다음 문제: !퀴즈"
        active['seen'].append(attempt)
        active['wrong'] += 1
        if active['wrong'] in (3,5,7,10):
            return '• 틀렸습니다! 새 힌트를 공개합니다.\n\n' + render(active)
        return f"• 틀렸습니다! · 오답 {active['wrong']}회"


@lru_cache(maxsize=1)
def service():
    return QuizService(QuizCatalog(), ROOT/'.quiz/quiz.sqlite3')
