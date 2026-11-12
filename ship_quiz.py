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
import unicodedata

from equipment_lookup import normalize
from initial_equipment import InitialEquipmentCatalog

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))  # Windows does not require a tzdata install.
NATIONS = {1: '일본', 2: '독일', 3: '이탈리아', 4: '미국', 5: '영국',
           6: '프랑스', 7: '소련', 8: '태국', 9: '노르웨이', 10: '스웨덴',
           11: '네덜란드', 12: '호주'}
STATS = [('火力最大', '화력'), ('雷装最大', '뇌장'), ('対空最大', '대공'),
         ('装甲最大', '장갑'), ('運初期', '운'), ('耐久初期', '내구')]
COMMANDS = {'!퀴즈', '!정답', '!퀴즈점수', '!퀴즈순위', '!퀴즈랭킹'}
RANKED_COOLDOWN_ROOM = '칸코레 진수부에 어서오세요'
RANKED_COOLDOWN_ROOM_ID = '18182686594126049'


def answer_cooldown(db, room, player, room_name):
    if str(room) != RANKED_COOLDOWN_ROOM_ID:
        return 15
    score = db.execute('SELECT points FROM scores WHERE room=? AND player=?', (room, player)).fetchone()
    if not score or score[0] <= 0:
        return 15
    # Competition ranking: ties share a rank (1, 1, 3), scoped to this room.
    rank = 1 + db.execute('SELECT COUNT(*) FROM scores WHERE room=? AND points>?', (room, score[0])).fetchone()[0]
    return {1: 60, 2: 40, 3: 30}.get(rank, 15)
SPEEDS = {0:'육상', 5:'저속', 10:'고속', 15:'고속+', 20:'최속'}
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
    return 10 + 5 * max(0, (min(hour, 24) - 16) // 2)


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
        speed_data = json.loads((root/'data/quiz_ship_speeds.json').read_text())
        if speed_data.get('schema') != 1:
            raise ValueError('Invalid quiz speed data')
        speeds = speed_data['speeds']
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
        candidates = []
        for sid, row in ships.items():
            info = meta[str(sid)]
            entries = equipment.starting_items(row)
            base_name = self.names.get(info['base'], self.names[sid])
            try:
                stats = {label: int(row[field]) for field, label in STATS if int(row[field]) > 0}
                luck = int(row['運初期'])
                hp = int(row['耐久初期'])
                stage = stage_label(row)
                slots = [int(row[f'搭載機数{i}']) for i in range(1,int(row['スロット数'])+1)]
            except ValueError:
                continue
            ship_class = classes.get(str(info['ship_class']))
            candidates.append(dict(sid=sid, family=info['base'], name=self.names[sid],
                base_name=base_name, nation=NATIONS.get(info['nationality'],'미확인'),
                kind=quiz_type(info['type']), stage=stage, stats=stats, luck=luck,
                hp=hp, speed=SPEEDS.get(speeds.get(str(sid))),
                class_hint=ship_class if info['type'] in (1,2) else None, slots=slots,
                equipment=[equipment.equipment.items[entry[0]]['name'] + (f' ★{entry[1]}' if entry[1] else '')
                           for entry in entries if entry is not None],
                equipment_unknown=None in entries,
                helpers=[equipment.equipment.items[i]['name'] for i in sorted(helper_items[sid])]))
        # Shared starting clues are allowed; subsequent hints narrow the answer.
        self.questions = []
        self.details = {q['sid']:q for q in candidates}
        for q in candidates:
            for pair in combinations(q['stats'], 2):
                self.questions.append({**q, 'stats': {label:q['stats'][label] for label in pair}})
        if not self.questions:
            raise ValueError('No eligible ship quiz questions')

    def choose(self, recent):
        pool = [q for q in self.questions if q['family'] not in recent] or self.questions
        families = sorted({q['family'] for q in pool})
        family = random.choice(families)
        return dict(random.choice([q for q in pool if q['family'] == family]))


def render(active):
    q = active['question']
    nation = '일본' if q['nation'] == '일본' else '해외'
    lines = [f"[칸무스 퀴즈 · {active['number']}/{active.get('limit',10)}]", '',
             f"· 함종: {q['kind']} / 국적: {nation}",
             f"· 개장: {q['stage']}"]
    equipment = ' / '.join(q['equipment'])
    if q.get('equipment_unknown'):
        equipment += ' / 일부 미확인' if equipment else '미확인'
    lines += ['', '💡 초기 장비: ' + (equipment or '없음')]
    wrong = active['wrong']
    if wrong >= 3:
        if q['kind'] in ('구축','해방'):
            lines += ['💡 함급: ' + (q.get('class_hint') or '미확인').split('(특',1)[0]]
        elif 'slots' in q:
            slots = q['slots']
            lines += ['💡 함재기 슬롯: ' + (' / '.join(map(str, slots)) if slots else '없음')]
    if wrong >= 5:
        lines += ['💡 개수 2번함 담당: ' + (' / '.join(q['helpers'][:3]) or '등록된 장비 없음')]
    if wrong >= 7:
        lines += ['💡 스탯: ' + ' / '.join(f'{k}: {v}' for k,v in q['stats'].items())]
    if wrong >= 10:
        if any('가'<=c<='힣' for c in q['base_name']):
            lines += ['💡 초성: ' + initials(q['base_name'])]
        else:
            latin = unicodedata.normalize('NFKD',q['base_name'])
            first = next((c.upper() for c in latin if c.isascii() and c.isalpha()),'')
            lines += ['💡 첫 알파벳: ' + (first or '미확인')]
    lines += ['', f'누적 오답: {wrong}회']
    return '\n'.join(lines)


class QuizReply(str):
    """Primary text plus ordered follow-up messages, without shared pending state."""
    def __new__(cls, text, followups=()):
        value = super().__new__(cls, text)
        value.followups = tuple(followups)
        return value


def next_quiz_hour(when):
    local = when.astimezone(KST)
    for hour in (3, 15, 18, 20, 22, 24):
        candidate = local.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
        if hour == 24:
            candidate += timedelta(days=1)
        if candidate > local:
            return f'{hour:02d}'
    return '03'


def ranking_text(db, room):
    rows = db.execute('SELECT name,points FROM scores WHERE room=? ORDER BY points DESC,name,player LIMIT 20', (room,)).fetchall()
    lines, previous, rank = [], None, 0
    for i, (name, points) in enumerate(rows, 1):
        if points != previous:
            rank = i
        lines.append(f'{rank}. {name} · {points}점')
        previous = points
    return '[칸무스 퀴즈 순위]\n\n' + ('\n'.join(lines) or '아직 정답자가 없습니다.')


class QuizService:
    def __init__(self, catalog, database, now=None):
        self.catalog, self.database = catalog, Path(database)
        self.now = now or (lambda: datetime.now(KST))
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS rooms (room TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scores (room TEXT, player TEXT, name TEXT, points INTEGER, PRIMARY KEY(room,player))')

    def handle(self, message, room, player='', name='', room_name=None):
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
            title = str(room_name if room_name is not None else room if room == RANKED_COOLDOWN_ROOM else '').strip()
            if title and not title.isdecimal():
                state['room_name'] = title
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
                    state['active']['limit'] = max(state['active']['number'],quota_limit(now))
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
        if command in ('!퀴즈점수', '!퀴즈순위', '!퀴즈랭킹'):
            return ranking_text(db, room)
        if command == '!퀴즈':
            if active:
                return render(active)
            limit = quota_limit(self.now())
            if state['count'] >= limit:
                return (f'✔️ 퀴즈 {limit}회를 모두 사용했습니다.\n✔️ 연습전 시간에 초기화됩니다.\n'
                        '✔️ 핫타임에 5회씩 추가됩니다.\n'
                        '    (18·20·22·24시에 각 5회 추가)')
            question = self.catalog.choose(state['recent'])
            state['count'] += 1
            state['recent'] = [*state['recent'], question['family']][-30:]
            state['active'] = dict(question=question, number=state['count'], wrong=0, seen=[], cooldowns={},
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
        cooldowns = active.setdefault('cooldowns', {})
        last = cooldowns.get(player)
        seconds = answer_cooldown(db, room, player, state.get('room_name', ''))
        if last is not None and timestamp-last < seconds:
            remaining = min(seconds,math.ceil(seconds-(timestamp-last)))
            return f'✔️ 정답 제출은 {seconds}초마다 가능합니다.\n✔️ {remaining}초 후 다시 시도해 주세요.'
        key = normalize(answer)
        families = self.catalog.answers.get(key, set())
        if len(families) > 1:
            return '여러 함선에 해당하는 이름입니다. 정확한 함선명으로 답해 주세요.'
        attempt = [player, key[:200]]
        if attempt in active['seen']:
            return '✔️ 이미 제출한 오답입니다.\n✔️ 오답 횟수는 늘어나지 않습니다.'
        cooldowns[player] = timestamp
        if q['family'] in families:
            db.execute('INSERT INTO scores VALUES (?,?,?,1) ON CONFLICT(room,player) DO UPDATE SET points=points+1,name=excluded.name', (room,player,name[:100]))
            points = db.execute('SELECT points FROM scores WHERE room=? AND player=?', (room,player)).fetchone()[0]
            state['active'] = None
            reply = f"🎉 {name[:100]}님 정답!\n정답: {q['name']}\n\n+1점 · 누적 {points}점"
            now = self.now()
            if state['count'] >= quota_limit(now):
                notice = ('퀴즈가 소진되었습니다.\n'
                          f'다음 퀴즈시간은 {next_quiz_hour(now)}시 입니다.\n\n'
                          + ranking_text(db, room))
                return QuizReply(reply, (notice,))
            return reply + '\n다음 문제: !퀴즈'
        active['seen'].append(attempt)
        active['wrong'] += 1
        if active['wrong'] in (3,5,7,10):
            return '• 틀렸습니다! 새 힌트를 공개합니다.\n\n' + render(active)
        return f"• 틀렸습니다! · 오답 {active['wrong']}회"


@lru_cache(maxsize=1)
def service():
    return QuizService(QuizCatalog(), ROOT/'.quiz/quiz.sqlite3')
