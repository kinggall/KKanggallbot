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
from ship_quiz import KST, QuizService, personal_start_period, quota_period, PERSONAL_START_ROOM_ID


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

    def send(self, command, player='a', room=PERSONAL_START_ROOM_ID, name='닉네임'):
        return self.service.handle(command, room, player, name)

    def solve(self, room=PERSONAL_START_ROOM_ID):
        self.assertIn('정답!', self.send('!정답 정답함', room=room))

    def state(self, room=PERSONAL_START_ROOM_ID):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT state FROM rooms WHERE room=?', (room,)).fetchone()
            return json.loads(row[0]) if row else None

    def seed(self, count, usage=None):
        state = dict(period=quota_period(self.date), day=self.date.date().isoformat(), count=count, active=None, recent=[])
        if usage is not None:
            state['personal_starts'] = usage
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO rooms VALUES (?,?)', (PERSONAL_START_ROOM_ID, json.dumps(state)))

    def test_five_issues_then_block_but_other_user_can_start_and_blocked_user_can_answer(self):
        for _ in range(5):
            self.assertIn('[칸무스 퀴즈', self.send('!퀴즈'))
            self.solve()
        self.assertEqual(self.send('!퀴즈', name='새 닉네임'),
                         '✔️ 개인 출제 횟수(5회) 소진')
        self.assertIn('6/10', self.send('!퀴즈', player='b'))
        self.solve()
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 5, 'b': 1})
        self.assertIn('6점', self.send('!퀴즈점수'))

    def test_each_question_batch_has_its_own_limit_even_when_all_refills_are_available(self):
        self.date = datetime(2026, 11, 16, 0, tzinfo=KST)
        for count, limit in ((0,5), (10,3), (15,3), (20,3), (25,3)):
            self.seed(count)
            for _ in range(limit):
                self.assertIn('[칸무스 퀴즈', self.send('!퀴즈'))
                self.solve()
            blocked = self.send('!퀴즈')
            self.assertEqual(blocked, f'✔️ 개인 출제 횟수({limit}회) 소진')
            self.assertEqual(self.state()['personal_starts']['players'], {'a': limit})
        self.assertEqual(personal_start_period(datetime(2026, 11, 15, 15, tzinfo=timezone.utc),25),
                         ('2026-11-15:15:questions:26', 3))

    def test_two_players_finish_sixteen_through_twenty_five_without_waiting_for_clock_reset(self):
        self.date = self.date.replace(hour=22)
        self.seed(15, {'period':'2026-11-15:22','players':{'a':3,'b':3}})
        issuers = ['a','a','a','b','b','a','a','a','b','b']
        for number, issuer in enumerate(issuers,16):
            self.assertIn(f'{number}/25',self.send('!퀴즈',player=issuer))
            self.solve()
            if number in (18,23):
                self.assertEqual(self.send('!퀴즈',player='a'),'✔️ 개인 출제 횟수(3회) 소진')
                self.assertEqual(self.state()['count'],number)
            if number == 20:
                self.service = QuizService(self.catalog,self.path,lambda:self.date)
        self.assertEqual(self.state()['count'],25)
        self.assertEqual(self.state()['personal_starts']['players'],{'a':3,'b':2})
        self.assertIn('questions:21',self.state()['personal_starts']['period'])
        self.assertIn('퀴즈 25회를 모두 사용',self.send('!퀴즈'))

    def test_clock_refills_do_not_reset_usage_until_question_batch_or_base_period_changes(self):
        for _ in range(5):
            self.send('!퀴즈');self.solve()
        for hour in (18,20,22):
            self.date = self.date.replace(hour=hour)
            self.assertEqual(self.send('!퀴즈'),'✔️ 개인 출제 횟수(5회) 소진')
            self.assertEqual(self.state()['count'],5)
        self.date = datetime(2026,11,16,3,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))
        self.assertEqual(self.state()['personal_starts']['players'],{'a':1})

    def test_old_clock_limits_at_twenty_four_can_finish_twenty_five_without_resetting_room(self):
        self.date = self.date.replace(hour=22)
        self.seed(24, {'period':'2026-11-15:22','players':{'a':3,'b':3}})
        self.assertIn('25/25', self.send('!퀴즈'))
        self.assertEqual(self.state()['personal_starts']['players'], {'a':1})
        self.solve()
        self.assertEqual(self.state()['count'],25)
        self.assertIn('퀴즈 25회를 모두 사용',self.send('!퀴즈',player='b'))

    def test_existing_problem_review_is_free_even_when_issuer_has_used_last_start(self):
        self.date = self.date.replace(hour=18)
        self.seed(10)
        for _ in range(2):
            self.send('!퀴즈'); self.solve()
        current = self.send('!퀴즈')
        for player in ('a', 'b', ''):
            self.assertEqual(current, self.send('!퀴즈', player=player))
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 3})
        self.assertEqual(self.state()['count'], 13)
        self.solve()
        self.assertEqual('✔️ 개인 출제 횟수(3회) 소진', self.send('!퀴즈'))

    def test_usage_survives_restart_and_is_separate_per_room(self):
        self.date = self.date.replace(hour=18)
        self.seed(10)
        for _ in range(3):
            self.send('!퀴즈'); self.solve()
        self.service = QuizService(self.catalog, self.path, lambda: self.date)
        self.assertEqual('✔️ 개인 출제 횟수(3회) 소진', self.send('!퀴즈'))
        self.assertIn('1/15', self.send('!퀴즈', room='other'))
        self.solve(room='other')
        for number in range(2,6):
            self.assertIn(f'{number}/15', self.send('!퀴즈', room='other'))
            self.solve(room='other')
        self.assertNotIn('personal_starts', self.state('other'))

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
            db.execute('INSERT INTO rooms VALUES (?,?)', (PERSONAL_START_ROOM_ID, json.dumps(state)))
        self.assertIn('10/10', self.send('!퀴즈'))
        self.assertEqual(self.state()['count'], 10)
        self.assertEqual(self.state()['personal_starts']['players'], {'a': 1})

    def test_room_title_alone_does_not_enable_limit_and_old_other_room_usage_is_ignored(self):
        state = dict(period='2026-11-15:15', day='2026-11-15', count=0, active=None, recent=[],
                     personal_starts={'period':'2026-11-15:15','players':{'a': 5}})
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO rooms VALUES (?,?)', ('other', json.dumps(state)))
        reply = self.service.handle('!퀴즈', 'other', 'a', '닉네임', room_name='칸코레 진수부에 어서오세요')
        self.assertIn('1/10', reply)
        self.assertEqual(self.state('other')['personal_starts'], state['personal_starts'])
