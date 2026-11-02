"""Locally reset one selected room's current practice-period quota, not scores."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ship_quiz import quota_period, KST


def reset(db, room, day):
    db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT state FROM rooms WHERE room=?', (room,)).fetchone()
    if not row:
        raise ValueError('Room not found')
    state = json.loads(row[0])
    if state.get('period',state.get('day')) != day:
        raise ValueError('Selected room has no quota used in this period')
    state['count'] = 0
    db.execute('UPDATE rooms SET state=? WHERE room=?', (json.dumps(state,ensure_ascii=False),room))


def main():
    path=ROOT/'.quiz/quiz.sqlite3'
    if not path.is_file():
        raise SystemExit('Quiz database not found on this PC.')
    day=quota_period(datetime.now(KST))
    with closing(sqlite3.connect(path,timeout=15)) as db:
        rooms=[]
        for room,raw in db.execute('SELECT room,state FROM rooms ORDER BY room'):
            state=json.loads(raw)
            if state.get('period')==day and state.get('count',0)>0:
                names=[r[0] for r in db.execute('SELECT name FROM scores WHERE room=? ORDER BY points DESC LIMIT 3',(room,))]
                rooms.append(room)
                print(f"{len(rooms)}. Room {room} | used {state['count']}/10 | players: {', '.join(names) or '-'}")
        if not rooms:
            print('No quota used this period. Nothing changed.')
            return
        choice=input('Reset which room? Enter its list number (blank cancels): ').strip()
        if not choice:
            return
        if not choice.isdecimal() or not 1<=int(choice)<=len(rooms):
            raise SystemExit('Invalid selection. Nothing changed.')
        with db:
            reset(db,rooms[int(choice)-1],day)
        print('Reset complete: 0/10 this period. Scores and active question preserved.')


if __name__=='__main__':
    main()
