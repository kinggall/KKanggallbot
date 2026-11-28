from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.delete_quiz_score import delete_score

ROOM = '18182686594126049'


class DeleteQuizScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'quiz.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE scores(room TEXT,player TEXT,name TEXT,points INTEGER,PRIMARY KEY(room,player))')
            db.execute('CREATE TABLE rooms(room TEXT PRIMARY KEY,state TEXT)')
            db.executemany('INSERT INTO scores VALUES (?,?,?,?)',
                           [(ROOM,'target','김보문 폰',12),(ROOM,'other','다른 유저',20),
                            ('other-room','target','김보문 폰',30),(ROOM,'partial','김보문 폰2',2)])
            db.execute('INSERT INTO rooms VALUES (?,?)',(ROOM,'{"count":25,"active":"question"}'))

    def read(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as db:
            return db.execute('SELECT * FROM scores ORDER BY room,player').fetchall(), db.execute('SELECT * FROM rooms').fetchall()

    def test_only_exact_room_and_player_deleted_and_full_backup_preserved(self):
        before, rooms = self.read()
        points, backup = delete_score(self.path, ROOM, '김보문 폰')
        self.assertEqual(points,12)
        self.assertEqual(self.read(backup),(before,rooms))
        self.assertEqual(self.read(),([r for r in before if r[:2]!=(ROOM,'target')],rooms))

    def test_missing_name_changes_nothing(self):
        before = self.read()
        self.assertIsNone(delete_score(self.path,ROOM,'없는 유저'))
        self.assertEqual(self.read(),before)
        self.assertFalse((self.path.parent/'backups').exists())

    def test_duplicate_name_refuses_to_choose_a_player(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO scores VALUES (?,?,?,?)',(ROOM,'duplicate','김보문 폰',7))
        before = self.read()
        with self.assertRaisesRegex(ValueError,'More than one'):
            delete_score(self.path,ROOM,'김보문 폰')
        self.assertEqual(self.read(),before)

    def test_wrong_path_never_creates_a_database(self):
        path = self.path.parent/'missing.sqlite3'
        with self.assertRaises(ValueError):
            delete_score(path,ROOM,'김보문 폰')
        self.assertFalse(path.exists())
