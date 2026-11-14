"""Personal issuing limits are independent of room quota and answer scores."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from equipment_lookup import normalize
from ship_quiz import KST, QuizService, personal_start_period


class PersonalStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'quiz.sqlite3'
        self.date = datetime(2026, 11, 15, 16, tzinfo=KST)
        question = dict(sid=1, family=1, name='정답함', base_name='정답함', nation='일본', kind='구축',
                        stage='미개장', stats={'화력': 1, '내구': 10}, equipment=[], helpers=[], class_hint='테스트형')
        self.catalog = Mock(answers={normalize('정답함'): {1}}, details={})
        self.catalog.choose.return_value = question
        self.service = QuizService(self.catalog, self.path, lambda: self.date)

    def send(self, command, player='a', room='r', name='닉네임'):
        return self.service.handle(command, room, player, name)

    def solve(self):
        self.assertIn('정답!', self.send('!정답 정답함'))

    def state(self, room='r'):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT state FROM rooms WHERE room=?', (room,)).fetchone()
            return json.loads(row[0]) if row else None

    def test_four_issues_then_block_but_other_user_can_start_and_blocked_user_can_answer(self):
        for _ in range(4):
            self.assertIn('[칸무스 퀴즈', self.send('!퀴즈'))
            self.solve()
        self.assertEqual(self.send('!퀴즈', name='새 닉네임'),
                         '✔️ 이번 시간대 출제 4회 소진\n✔️ 다음 출제: 18시')
        self.assertIn('5/10', self.send('!퀴즈', player='b'))
        self.solve()
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 4, 'b': 1})
        self.assertIn('5점', self.send('!퀴즈점수'))

    def test_all_kst_windows_reset_to_their_own_limit_without_carryover(self):
        windows = [(15, 2, 2, '03'), (15, 3, 4, '15'), (15, 15, 4, '18'),
                   (15, 18, 2, '20'), (15, 20, 2, '22'), (15, 22, 2, '24'), (16, 0, 2, '03')]
        for day, hour, limit, next_hour in windows:
            self.date = datetime(2026, 11, day, hour, tzinfo=KST)
            for _ in range(limit):
                self.assertIn('[칸무스 퀴즈', self.send('!퀴즈'))
                self.solve()
            blocked = self.send('!퀴즈')
            self.assertIn(f'출제 {limit}회 소진', blocked)
            self.assertIn(f'{next_hour}시', blocked)
            self.assertEqual(self.state()['personal_starts']['players'], {'a': limit})
        self.assertEqual(personal_start_period(datetime(2026, 11, 15, 15, tzinfo=timezone.utc)),
                         ('2026-11-16:00', 2))

    def test_existing_problem_review_is_free_even_when_issuer_has_used_last_start(self):
        self.date = self.date.replace(hour=18)
        self.send('!퀴즈'); self.solve()
        current = self.send('!퀴즈')
        for player in ('a', 'b', ''):
            self.assertEqual(current, self.send('!퀴즈', player=player))
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 2})
        self.assertEqual(self.state()['count'], 2)
        self.solve()
        self.assertIn('출제 2회 소진', self.send('!퀴즈'))

    def test_usage_survives_restart_and_is_separate_per_room(self):
        self.date = self.date.replace(hour=18)
        for _ in range(2):
            self.send('!퀴즈'); self.solve()
        self.service = QuizService(self.catalog, self.path, lambda: self.date)
        self.assertIn('출제 2회 소진', self.send('!퀴즈'))
        self.assertIn('1/15', self.send('!퀴즈', room='other'))
        self.assertEqual(self.state('other')['personal_starts']['players'], {'a': 1})

    def test_simultaneous_commands_charge_only_the_single_successful_issuer(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda p: self.send('!퀴즈', player=p), ('a', 'b')))
        self.assertEqual(results[0], results[1])
        state = self.state()
        self.assertEqual(state['count'], 1)
        self.assertEqual(sum(state['personal_starts']['players'].values()), 1)

    def test_missing_identity_only_prevents_new_issue_and_never_consumes_quota(self):
        for player in ('', 'name:닉네임'):
            self.assertIn('참가자 정보', self.send('!퀴즈', player=player))
        self.assertEqual(self.state()['count'], 0)
        self.assertNotIn('personal_starts', self.state())

    def test_failed_question_generation_rolls_back_both_counters(self):
        self.catalog.choose.side_effect = ValueError('fixture failure')
        with self.assertRaises(ValueError):
            self.send('!퀴즈')
        self.assertIsNone(self.state())
        self.catalog.choose.side_effect = None
        self.assertIn('1/10', self.send('!퀴즈'))
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 1})

    def test_old_room_state_is_preserved_without_guessing_previous_issuers(self):
        state = dict(period='2026-11-15:15', day='2026-11-15', count=9, active=None, recent=[1])
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO rooms VALUES (?,?)', ('r', json.dumps(state)))
        self.assertIn('10/10', self.send('!퀴즈'))
        self.assertEqual(self.state()['count'], 10)
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 1})
