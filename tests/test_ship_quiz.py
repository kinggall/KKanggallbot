"""Real data eligibility, persistent room state and concurrent scoring."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from equipment_lookup import normalize
from ship_quiz import QuizCatalog, QuizService, render

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo('Asia/Seoul')


class QuizTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = QuizCatalog(ROOT)
        cls.question = next(q for q in cls.catalog.questions if q['sid'] == 656)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'quiz.sqlite3'
        self.date = datetime(2026,11,2,23,59,tzinfo=KST)
        self.service = QuizService(self.catalog, self.database, lambda:self.date)
        self.chooser = patch.object(self.catalog, 'choose', return_value=dict(self.question))
        self.chooser.start()
        self.addCleanup(self.chooser.stop)

    def send(self, msg, room='r1', player='u1', name='참가자'):
        return self.service.handle(msg,room,player,name)

    def test_real_renames_remodels_aliases_and_stage_mask(self):
        for answer in ['유키카제', '단양', '유키카제 개2', '雪風', '丹陽']:
            self.assertEqual(self.catalog.answers[normalize(answer)], {20})
        self.assertEqual(self.catalog.answers[normalize('뽀이')], self.catalog.answers[normalize('유다치')])
        gotland = next(q for q in self.catalog.questions if q['sid'] == 630)
        self.assertEqual(gotland['stage'], '개2 이상')
        text = render(dict(question=gotland,number=1,wrong=0))
        self.assertNotIn('andra',text)
        self.assertNotIn('고틀란드',text)
        for question in self.catalog.questions:
            self.assertEqual(len(question['stats']),2)
            self.assertTrue(question['equipment'])
            self.assertTrue(question['helpers'])

    def test_active_question_cannot_be_replaced_or_cost_another_turn(self):
        first = self.send('!퀴즈')
        self.assertIn('1/10',first)
        self.assertNotIn('유키카제',first)
        self.assertIn(first,self.send('!퀴즈'))
        self.assertIn('1/10',self.send('!힌트'))
        self.send('!포기')
        self.assertIn('2/10',self.send('!퀴즈'))

    def test_hints_at_three_five_seven_and_repeated_wrong_dedup(self):
        self.send('!퀴즈')
        self.assertIn('오답 1회',self.send('!정답 모르겠음'))
        self.assertIn('이미 제출',self.send('!정답 모 르겠음!'))
        self.assertIn('오답 2회',self.send('!정답 모르겠음',player='u2'))
        third=self.send('!정답 틀린답3')
        self.assertIn('개수 2번함 담당',third)
        self.assertNotIn('💡 초기 장비',third)
        self.send('!정답 틀린답4')
        fifth=self.send('!정답 틀린답5')
        self.assertIn('💡 초기 장비',fifth)
        self.assertNotIn('💡 초성',fifth)
        self.send('!정답 틀린답6')
        seventh=self.send('!정답 틀린답7')
        self.assertIn('💡 초성: ㅇㅋㅋㅈ',seventh)
        self.assertIn('오답 8회',self.send('!정답 틀린답8'))
        self.assertIn('정답!',self.send('!정답 단양'))

    def test_quota_room_isolation_and_midnight(self):
        for n in range(1,11):
            self.assertIn(f'{n}/10',self.send('!퀴즈'))
            self.send('!포기')
        self.assertIn('모두 사용',self.send('!퀴즈'))
        self.assertIn('1/10',self.send('!퀴즈',room='r2'))
        self.date = datetime(2026,11,3,0,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_midnight_retains_active_question_but_resets_quota(self):
        self.send('!퀴즈')
        self.send('!정답 오답')
        self.date = datetime(2026,11,3,0,0,tzinfo=KST)
        self.assertIn('진행 중',self.send('!퀴즈'))
        self.assertIn('누적 오답: 1회',self.send('!힌트'))
        self.send('!정답 단양')
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_restart_preserves_progress_quota_and_scores(self):
        self.send('!퀴즈')
        self.send('!정답 단양')
        self.send('!퀴즈')
        self.send('!정답 틀림')
        self.service=QuizService(self.catalog,self.database,lambda:self.date)
        self.assertIn('2/10',self.send('!퀴즈'))
        self.assertIn('누적 오답: 1회',self.send('!힌트'))
        self.assertIn('참가자 · 1점',self.send('!퀴즈점수'))
        self.assertNotIn('참가자 · 1점',self.send('!퀴즈점수',room='r2'))

    def test_identity_validation_and_ambiguous_alias(self):
        self.assertIn('채팅방 정보',self.send('!퀴즈',room=''))
        self.send('!퀴즈')
        self.assertIn('참가자 정보',self.send('!정답 단양',player=''))
        self.assertIn('사용법',self.send('!정답'))
        with patch.dict(self.catalog.answers,{normalize('모호함'):{20,30}}):
            self.assertIn('정확한 함선명',self.send('!정답 모호함'))
        self.assertIn('누적 오답: 0회',self.send('!힌트'))

    def test_concurrent_correct_awards_exactly_one_point(self):
        self.send('!퀴즈')
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda u:self.send('!정답 단양',player=u,name=u),['a','b']))
        self.assertEqual(sum('정답!' in r for r in results),1)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT SUM(points) FROM scores').fetchone()[0],1)

    def test_concurrent_starts_use_one_question(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _:self.send('!퀴즈'),range(2)))
        self.send('!포기')
        self.assertIn('2/10',self.send('!퀴즈'))

    def test_correct_replay_no_extra_point_and_name_change_keeps_identity(self):
        self.send('!퀴즈')
        self.send('!정답 단양',name='이전이름')
        self.assertIn('진행 중인 문제가 없습니다',self.send('!정답 유키카제'))
        self.send('!퀴즈')
        self.send('!정답 유키카제 개2',name='새이름')
        board=self.send('!퀴즈점수')
        self.assertIn('새이름 · 2점',board)
        self.assertNotIn('이전이름',board)

    def test_unrelated_message_and_failed_start_do_not_consume_quota(self):
        self.assertIsNone(self.send('안녕'))
        with patch.object(self.catalog,'choose',side_effect=ValueError('no question')):
            with self.assertRaises(ValueError):
                self.send('!퀴즈')
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_utc_date_crosses_korean_midnight(self):
        from datetime import timezone
        self.send('!퀴즈')
        self.send('!포기')
        self.date=datetime(2026,11,2,15,0,tzinfo=timezone.utc)
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_webhook_routes_and_sender_identity(self):
        import bot
        with patch.object(bot.ship_quiz,'service',return_value=self.service), patch.object(bot.requests,'post') as post:
            client=bot.app.test_client()
            for message in ['!퀴즈','!정답 단양','!퀴즈점수']:
                result=client.post('/webhook',json={'msg':message,'sender':'테스터','json':{'chat_id':'web','user_id':'stable-id'}})
                self.assertEqual(result.status_code,200)
            self.assertIn('테스터 · 1점',post.call_args.kwargs['json']['data'])
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT player FROM scores').fetchone()[0],'stable-id')


if __name__=='__main__':
    unittest.main()
