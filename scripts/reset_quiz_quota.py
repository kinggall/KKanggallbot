"""Locally reset one selected room's current practice-period quota, not scores."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ship_quiz import quota_period, quota_limit, KST


def reset(db, room, day, restore=None):
    if restore is not None and (not isinstance(restore, int) or isinstance(restore, bool) or restore <= 0):
        raise ValueError('Restore amount must be a positive integer')
    db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT state FROM rooms WHERE room=?', (room,)).fetchone()
    if not row:
        raise ValueError('Room not found')
    state = json.loads(row[0])
    if state.get('period',state.get('day')) != day:
        raise ValueError('Selected room has no quota used in this period')
    state['count'] = 0 if restore is None else max(0, state['count'] - restore)
    db.execute('UPDATE rooms SET state=? WHERE room=?', (json.dumps(state,ensure_ascii=False),room))
    return state['count']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore',type=int,help='Restore only this many used attempts instead of resetting all')
    args=parser.parse_args()
    if args.restore is not None and args.restore<=0:
        parser.error('--restore must be positive')
    path=ROOT/'.quiz/quiz.sqlite3'
    if not path.is_file():
        raise SystemExit('Quiz database not found on this PC.')
    now=datetime.now(KST)
    day=quota_period(now)
    limit=quota_limit(now)
    with closing(sqlite3.connect(path,timeout=15)) as db:
        rooms=[]
        for room,raw in db.execute('SELECT room,state FROM rooms ORDER BY room'):
            state=json.loads(raw)
            if state.get('period')==day and state.get('count',0)>0:
                names=[r[0] for r in db.execute('SELECT name FROM scores WHERE room=? ORDER BY points DESC LIMIT 3',(room,))]
                rooms.append(room)
                print(f"{len(rooms)}. Room {room} | {state.get('room_name','')} | used {state['count']}/{limit} | players: {', '.join(names) or '-'}")
        if not rooms:
            print('No quota used this period. Nothing changed.')
            return
        choice=input('Select room number (blank cancels): ').strip()
        if not choice:
            return
        if not choice.isdecimal() or not 1<=int(choice)<=len(rooms):
            raise SystemExit('Invalid selection. Nothing changed.')
        with db:
            count=reset(db,rooms[int(choice)-1],quota_period(datetime.now(KST)),restore=args.restore)
        print(f'Complete: used {count}/{quota_limit(datetime.now(KST))}. Scores and active question preserved.')


if __name__=='__main__':
    main()
