import json
import sqlite3
import unittest
from scripts.reset_quiz_quota import reset


class ResetQuizTests(unittest.TestCase):
    def test_only_selected_room_daily_count_changes(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE rooms (room TEXT PRIMARY KEY,state TEXT)')
        db.execute('CREATE TABLE scores (room TEXT,points INTEGER)')
        state={'day':'2026-11-02','count':10,'active':{'wrong':5},'recent':[20]}
        for room in ['chosen','other']:
            db.execute('INSERT INTO rooms VALUES (?,?)',(room,json.dumps(state)))
            db.execute('INSERT INTO scores VALUES (?,9)',(room,))
        db.commit()
        with db:
            reset(db,'chosen','2026-11-02')
        updated=json.loads(db.execute("SELECT state FROM rooms WHERE room='chosen'").fetchone()[0])
        self.assertEqual(updated,{**state,'count':0})
        self.assertEqual(json.loads(db.execute("SELECT state FROM rooms WHERE room='other'").fetchone()[0]),state)
        self.assertEqual(db.execute('SELECT SUM(points) FROM scores').fetchone()[0],18)
        with self.assertRaises(ValueError), db:
            reset(db,'chosen','2026-11-03')
