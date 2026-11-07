import json
import sqlite3
import unittest
from scripts.reset_quiz_quota import reset


class ResetQuizTests(unittest.TestCase):
    def test_restore_five_preserves_other_state_and_rooms(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE rooms (room TEXT PRIMARY KEY,state TEXT)')
            state={'period':'2026-11-07:15','count':25,'active':{'wrong':3,'cooldowns':{'u':1}},'recent':[20]}
            db.executemany('INSERT INTO rooms VALUES (?,?)',[(r,json.dumps(state)) for r in ('chosen','other')])
            db.commit()
            with db:
                self.assertEqual(reset(db,'chosen','2026-11-07:15',restore=5),20)
            got=json.loads(db.execute('SELECT state FROM rooms WHERE room=?',('chosen',)).fetchone()[0])
            self.assertEqual(got,{**state,'count':20})
            self.assertEqual(json.loads(db.execute('SELECT state FROM rooms WHERE room=?',('other',)).fetchone()[0]),state)
            with db:
                self.assertEqual(reset(db,'chosen','2026-11-07:15',restore=30),0)
            with self.assertRaises(ValueError), db:
                reset(db,'chosen','2026-11-07:15',restore=-1)

    def test_only_selected_room_daily_count_changes(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE rooms (room TEXT PRIMARY KEY,state TEXT)')
        db.execute('CREATE TABLE scores (room TEXT,points INTEGER)')
        state={'day':'2026-11-02','period':'2026-11-02:15','count':10,'active':{'wrong':5},'recent':[20]}
        for room in ['chosen','other']:
            db.execute('INSERT INTO rooms VALUES (?,?)',(room,json.dumps(state)))
            db.execute('INSERT INTO scores VALUES (?,9)',(room,))
        db.commit()
        with db:
            reset(db,'chosen','2026-11-02:15')
        updated=json.loads(db.execute("SELECT state FROM rooms WHERE room='chosen'").fetchone()[0])
        self.assertEqual(updated,{**state,'count':0})
        self.assertEqual(json.loads(db.execute("SELECT state FROM rooms WHERE room='other'").fetchone()[0]),state)
        self.assertEqual(db.execute('SELECT SUM(points) FROM scores').fetchone()[0],18)
        with self.assertRaises(ValueError), db:
            reset(db,'chosen','2026-11-03:03')
