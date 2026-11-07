"""Real data eligibility, persistent room state and concurrent scoring."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from equipment_lookup import normalize
from ship_quiz import QuizCatalog, QuizService, render, quiz_type, NATIONS, STATS, stage_label

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
        self.date = datetime(2026,11,2,16,0,tzinfo=KST)
        self.service = QuizService(self.catalog, self.database, lambda:self.date)
        self.chooser = patch.object(self.catalog, 'choose', return_value=dict(self.question))
        self.chooser.start()
        self.addCleanup(self.chooser.stop)

    def send(self, msg, room='r1', player='u1', name='참가자'):
        reply=self.service.handle(msg,room,player,name)
        if msg.startswith('!정답 '):
            self.date += timedelta(seconds=20)
        return reply

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
            self.assertIsInstance(question['equipment'],list)
            self.assertIsInstance(question['helpers'],list)
            self.assertTrue(set(question['stats']) <= {'화력','뇌장','대공','장갑'})
            self.assertTrue(all(v>0 for v in question['stats'].values()))
            self.assertGreater(question['hp'],0)
            self.assertIn(question['speed'],('저속','고속','고속+','최속','육상'))

    def test_foreign_nationality_is_hidden_for_new_and_saved_questions(self):
        for original in ['미국','독일','영국','이탈리아','프랑스','태국','노르웨이','스웨덴','호주','네덜란드','소련']:
            text=render({'question':{**self.question,'nation':original},'number':1,'wrong':0})
            self.assertIn('국적: 해외',text)
            self.assertNotIn(original,text)
        self.assertIn('국적: 일본',render({'question':self.question,'number':1,'wrong':0}))

    def test_luck_hp_speed_are_selected_at_question_creation(self):
        for extra in [('운',63),('내구',35),('속력','고속')]:
            with patch('ship_quiz.random.choice',side_effect=[self.question['family'],self.question,extra]):
                selected=QuizCatalog.choose(self.catalog,[])
            self.assertEqual(selected['extra'],extra)
            self.assertNotIn('extra',self.question)
            text=render({'question':selected,'number':1,'wrong':0})
            self.assertIn(f'· {extra[0]}: {extra[1]} (Lv 99 기준)',text)
            if extra[0]!='운':
                self.assertNotIn('· 운:',text)

    def test_selected_extra_clue_does_not_reroll_on_review_or_restart(self):
        selected={**self.question,'extra':('내구',35)}
        with patch.object(self.catalog,'choose',return_value=selected):
            first=self.send('!퀴즈')
        self.assertEqual(first,self.send('!퀴즈'))
        self.service=QuizService(self.catalog,self.database,lambda:self.date)
        self.assertEqual(first,self.send('!퀴즈'))
        self.assertIn('· 내구: 35',first)

    def test_speed_and_hp_use_base_data_not_equipment_or_marriage(self):
        self.assertEqual(self.catalog.details[656]['hp'],35)
        self.assertEqual(self.catalog.details[656]['speed'],'고속')
        self.assertEqual(self.catalog.details[131]['speed'],'저속')
        self.assertEqual(self.catalog.details[299]['speed'],'저속')

    def test_broad_ship_categories(self):
        groups = {'전함':[8,9,10,12], '항모':[7,11,18], '중순':[5,6],
                  '경순':[3,4,21], '구축':[2], '잠수':[13,14], '해방':[1],
                  '기타함종':[0,15,16,17,19,20,22,999]}
        for name, types in groups.items():
            for ship_type in types:
                self.assertEqual(quiz_type(ship_type),name)
        self.assertTrue({q['kind'] for q in self.catalog.questions} <= set(groups))

    def test_all_csv_families_and_forms_are_included_without_hint_exclusions(self):
        meta=json.loads((ROOT/'data/fit_metadata.json').read_text())['ships']
        self.assertEqual({q['family'] for q in self.catalog.questions},{r['base'] for r in meta.values()})
        self.assertEqual(set(self.catalog.details),{int(sid) for sid in meta})
        self.assertTrue(any(not q['helpers'] for q in self.catalog.questions))
        self.assertTrue(any(not q['equipment'] and not q['equipment_unknown'] for q in self.catalog.questions))
        with patch('ship_quiz.InitialEquipmentCatalog.starting_items',return_value=[None]):
            unverified=QuizCatalog(ROOT)
        self.assertEqual(set(unverified.details),set(self.catalog.details))
        self.assertTrue(all(q['equipment_unknown'] for q in unverified.questions))
        self.assertEqual(NATIONS[8],'태국')
        self.assertEqual(NATIONS[9],'노르웨이')
        self.assertEqual(NATIONS[12],'호주')

    def test_missing_hints_are_explicit_without_revealing_untranslated_name(self):
        question={**self.question,'equipment':[],'helpers':[],'base_name':'Norge','class_hint':None}
        text=render({'question':question,'wrong':10,'number':1})
        self.assertIn('💡 초기 장비: 없음',text)
        self.assertIn('💡 개수 2번함 담당: 등록된 장비 없음',text)
        self.assertIn('💡 함급: 미확인',text)
        self.assertIn('💡 첫 알파벳: N',text)
        self.assertNotIn('Norge',text)
        self.assertNotIn('💡 함재기 슬롯',text)
        question['equipment_unknown']=True
        text=render({'question':question,'wrong':3,'number':1})
        self.assertIn('💡 초기 장비: 미확인',text)
        question['equipment']=['테스트 장비']
        text=render({'question':question,'wrong':3,'number':1})
        self.assertIn('💡 초기 장비: 테스트 장비 / 일부 미확인',text)

    def test_latin_name_hint_reveals_only_one_letter_at_ten_misses(self):
        for name,letter in [('Scamp','S'),('Z1','Z'),('U-511','U'),('Algérie','A'),
                            ('Béarn','B'),('Éclair','E'),('C.Cappellini','C')]:
            question={**self.question,'base_name':name}
            text=render({'question':question,'wrong':10,'number':1})
            self.assertIn(f'💡 첫 알파벳: {letter}\n',text)
            self.assertNotIn('원문 ',text)
            self.assertNotIn(name,text)
            self.assertNotIn('💡 초성:',text)
            self.assertNotIn('💡 첫 알파벳:',render({'question':question,'wrong':9,'number':1}))

    def test_overlapping_starting_clues_are_allowed_and_all_pairs_included(self):
        from collections import defaultdict
        from itertools import combinations
        signatures=defaultdict(set)
        actual=defaultdict(set)
        for question in self.catalog.questions:
            (a,x),(b,y)=question['stats'].items()
            key=(question['kind'],question['nation'],question['stage'],question['luck'],a,x,b,y)
            signatures[key].add(question['family'])
            actual[question['sid']].add((a,b))
        self.assertTrue(any(len(families)>1 for families in signatures.values()))
        for sid,detail in self.catalog.details.items():
            self.assertEqual(actual[sid],set(combinations(detail['stats'],2)))

    def test_active_question_cannot_be_replaced_or_cost_another_turn(self):
        first = self.send('!퀴즈')
        self.assertIn('1/10',first)
        self.assertNotIn('유키카제',first)
        self.assertIn(first,self.send('!퀴즈'))
        self.assertIn('1/10',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.assertIn('2/10',self.send('!퀴즈'))

    def test_hints_at_three_five_seven_ten_and_repeated_wrong_dedup(self):
        self.send('!퀴즈')
        self.assertIn('오답 1회',self.send('!정답 모르겠음'))
        self.assertEqual(self.send('!정답 모 르겠음!'),
                         '✔️ 이미 제출한 오답입니다.\n✔️ 오답 횟수는 늘어나지 않습니다.')
        self.assertIn('오답 2회',self.send('!정답 모르겠음',player='u2'))
        third=self.send('!정답 틀린답3')
        self.assertIn('💡 초기 장비',third)
        self.assertNotIn('개수 2번함 담당',third)
        self.send('!정답 틀린답4')
        fifth=self.send('!정답 틀린답5')
        self.assertIn('개수 2번함 담당',fifth)
        self.assertNotIn('💡 초성',fifth)
        self.send('!정답 틀린답6')
        seventh=self.send('!정답 틀린답7')
        self.assertIn('💡 함급: 카게로형',seventh)
        self.assertNotIn('💡 초성',seventh)
        self.assertIn('오답 8회',self.send('!정답 틀린답8'))
        self.send('!정답 틀린답9')
        self.assertIn('💡 초성: ㅇㅋㅋㅈ',self.send('!정답 틀린답10'))
        self.assertIn('정답!',self.send('!정답 단양'))

    def test_quota_room_isolation_and_morning_reset(self):
        for n in range(1,11):
            self.assertIn(f'{n}/10',self.send('!퀴즈'))
            self.send('!정답 단양')
        self.assertEqual(self.send('!퀴즈'),
                         '✔️ 퀴즈 10회를 모두 사용했습니다.\n✔️ 연습전 시간에 초기화됩니다.\n✔️ 핫타임에 5회씩 추가됩니다.\n    (18·20·22·24시에 각 5회 추가)')
        self.assertIn('1/10',self.send('!퀴즈',room='r2'))
        self.date = datetime(2026,11,3,3,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_period_change_retains_active_question_but_resets_quota(self):
        self.send('!퀴즈')
        self.send('!정답 오답')
        self.date = datetime(2026,11,3,3,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))
        self.assertIn('누적 오답: 1회',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_restart_preserves_progress_quota_and_scores(self):
        self.send('!퀴즈')
        self.send('!정답 단양')
        self.send('!퀴즈')
        self.send('!정답 틀림')
        self.service=QuizService(self.catalog,self.database,lambda:self.date)
        self.assertIn('2/10',self.send('!퀴즈'))
        self.assertIn('누적 오답: 1회',self.send('!퀴즈'))
        self.assertIn('참가자 · 1점',self.send('!퀴즈점수'))
        self.assertNotIn('참가자 · 1점',self.send('!퀴즈점수',room='r2'))

    def test_identity_validation_and_ambiguous_alias(self):
        self.assertIn('채팅방 정보',self.send('!퀴즈',room=''))
        self.send('!퀴즈')
        self.assertIn('참가자 정보',self.send('!정답 단양',player=''))
        self.assertIn('사용법',self.send('!정답'))
        with patch.dict(self.catalog.answers,{normalize('모호함'):{20,30}}):
            self.assertIn('정확한 함선명',self.send('!정답 모호함'))
        self.assertIn('누적 오답: 0회',self.send('!퀴즈'))

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
        self.send('!정답 단양')
        self.assertIn('2/10',self.send('!퀴즈'))

    def test_correct_replay_no_extra_point_and_name_change_keeps_identity(self):
        self.send('!퀴즈')
        self.send('!정답 단양',name='이전이름')
        self.assertEqual(self.send('!정답 유키카제'),
                         '✔️ 진행 중인 문제가 없습니다.\n✔️ !퀴즈로 시작해 주세요.')
        self.send('!퀴즈')
        self.send('!정답 유키카제 개2',name='새이름')
        board=self.send('!퀴즈점수')
        self.assertIn('새이름 · 2점',board)
        self.assertNotIn('이전이름',board)

    def test_recovered_nickname_repairs_existing_score_without_reset(self):
        self.send('!퀴즈')
        self.send('!정답 단양',name='')
        self.assertIn('참가자 · 1점',self.send('!퀴즈점수',name=''))
        self.assertIn('복구된닉 · 1점',self.send('!퀴즈점수',name='복구된닉'))
        self.send('!퀴즈',name='')
        self.assertIn('복구된닉님 정답!',self.send('!정답 단양',name=''))
        self.assertIn('복구된닉 · 2점',self.send('!퀴즈점수',name=''))

    def test_cooldown_is_per_room_player_persistent_and_exactly_fifteen_seconds(self):
        self.send('!퀴즈')
        def answer(text,player='u1',room='r1'):
            return self.service.handle('!정답 '+text,room,player,'참가자')
        self.assertIn('오답 1회',answer('오답첫번째'))
        self.assertIn('15초 후',answer('단양'))
        self.date+=timedelta(seconds=1)
        self.assertEqual(answer('단양'),'✔️ 정답 제출은 15초마다 가능합니다.\n✔️ 14초 후 다시 시도해 주세요.')
        self.date+=timedelta(seconds=13)
        self.service=QuizService(self.catalog,self.database,lambda:self.date)
        self.assertIn('1초 후',answer('단양'))
        self.assertIn('누적 오답: 1회',self.send('!퀴즈'))
        self.assertIn('오답 2회',answer('다른사람답',player='u2'))
        self.send('!퀴즈',room='r2')
        self.assertIn('오답 1회',answer('다른방답',room='r2'))
        self.date+=timedelta(seconds=1)
        self.assertIn('정답!',answer('단양'))
        self.send('!퀴즈')
        self.assertIn('정답!',answer('단양'))
        self.assertIn('참가자 · 2점',self.send('!퀴즈점수'))

    def test_new_question_clears_cooldowns_for_every_player(self):
        self.send('!퀴즈')
        def answer(text,player):
            return self.service.handle('!정답 '+text,'r1',player,player)
        self.assertIn('오답 1회',answer('첫답오답','a'))
        self.assertIn('오답 2회',answer('둘째오답','b'))
        self.assertIn('15초 후',answer('재시도','a'))
        self.assertIn('정답!',answer('단양','winner'))
        self.send('!퀴즈')
        self.assertIn('오답 1회',answer('첫답오답','a'))
        self.assertIn('오답 2회',answer('둘째오답','b'))
        self.assertIn('정답!',answer('단양','winner'))

    def test_target_room_rank_cooldowns_and_exact_boundaries(self):
        title = '칸코레 진수부에 어서오세요'
        for player, points, seconds in [('first',9,60),('second',7,40),('third',5,30),('fourth',2,15),('zero',0,15)]:
            room = 'rank-' + player
            with sqlite3.connect(self.database) as db:
                db.executemany('INSERT INTO scores VALUES (?,?,?,?)',
                    [(room,p,p,n) for p,n in [('first',9),('second',7),('third',5),('fourth',2),('zero',0)]])
            self.service.handle('!퀴즈', room, player, player, room_name=title)
            self.service.handle('!정답 틀린답', room, player, player)
            reply = self.service.handle('!정답 단양', room, player, player)
            self.assertIn(f'{seconds}초마다', reply)
            self.date += timedelta(seconds=seconds-1)
            self.assertIn('1초 후', self.service.handle('!정답 단양',room,player,player))
            self.date += timedelta(seconds=1)
            self.assertIn('정답!', self.service.handle('!정답 단양',room,player,player))
            self.service.handle('!퀴즈',room,player,player)
            self.assertIn('정답!',self.service.handle('!정답 단양',room,player,player))

    def test_ties_room_scope_zero_scores_and_rank_changes(self):
        from ship_quiz import answer_cooldown, RANKED_COOLDOWN_ROOM
        with sqlite3.connect(self.database) as db:
            db.executemany('INSERT INTO scores VALUES (?,?,?,?)',
                [('r1',p,p,n) for p,n in [('a',8),('b',8),('c',7),('d',0)]])
            self.assertEqual(answer_cooldown(db,'r1','a',RANKED_COOLDOWN_ROOM),60)
            self.assertEqual(answer_cooldown(db,'r1','b',RANKED_COOLDOWN_ROOM),60)
            self.assertEqual(answer_cooldown(db,'r1','c',RANKED_COOLDOWN_ROOM),30)
            self.assertEqual(answer_cooldown(db,'r1','d',RANKED_COOLDOWN_ROOM),15)
            self.assertEqual(answer_cooldown(db,'r1','a','다른 방'),15)
            self.assertEqual(answer_cooldown(db,'r2','a',RANKED_COOLDOWN_ROOM),15)
            db.execute('UPDATE scores SET points=0 WHERE room=?',('r1',))
            self.assertEqual(answer_cooldown(db,'r1','a',RANKED_COOLDOWN_ROOM),15)
            db.execute('UPDATE scores SET points=1 WHERE player=?',('c',))
            self.assertEqual(answer_cooldown(db,'r1','c',RANKED_COOLDOWN_ROOM),60)

    def test_webhook_passes_room_title_with_numeric_chat_id(self):
        import bot
        title = '칸코레 진수부에 어서오세요'
        with patch.object(bot.ship_quiz, 'service') as factory, patch.object(bot.iris_identity, 'identity', return_value=('u1','닉')), patch.object(bot.requests, 'post'):
            factory.return_value.handle.return_value = '퀴즈'
            response = bot.app.test_client().post('/webhook', json={'msg':'!퀴즈','room':title,'json':{'chat_id':'12345'}})
            self.assertEqual(response.status_code,200)
            factory.return_value.handle.assert_called_once_with('!퀴즈','12345','u1','닉',room_name=title)

    def test_legacy_room_wide_cooldown_does_not_block_new_questions(self):
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (room TEXT,player TEXT,submitted REAL,PRIMARY KEY(room,player))')
            db.execute('INSERT INTO attempts VALUES (?,?,?)',('r1','u1',self.date.timestamp()))
        self.send('!퀴즈')
        self.assertIn('정답!',self.service.handle('!정답 단양','r1','u1','참가자'))

    def test_seventh_hint_classes_special_destroyers_and_aircraft_slots(self):
        for cid,label in [(12,'후부키형'),(1,'아야나미형'),(5,'아카츠키형'),(117,'우쿠루형')]:
            classes=json.loads((ROOT/'data/quiz_ship_classes.json').read_text())['classes']
            self.assertEqual(classes[str(cid)],label)
        cruiser=next(q for q in self.catalog.questions if q['sid']==630)
        text=render({'question':cruiser,'wrong':7,'number':1})
        self.assertIn('💡 함재기 슬롯: 2 / 2 / 3 / 7\n',text)
        self.assertNotIn('(총 ',text)
        self.assertNotIn('💡 초성',text)
        self.assertNotIn('💡 함급',text)
        legacy={**self.question,'class_hint':'후부키형(특Ⅰ형)'}
        legacy_text=render({'question':legacy,'wrong':7,'number':1})
        self.assertIn('💡 함급: 후부키형\n',legacy_text)
        self.assertNotIn('(특',legacy_text)

    def test_concurrent_wrong_answers_share_one_cooldown(self):
        self.send('!퀴즈')
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies=list(executor.map(lambda text:self.service.handle('!정답 '+text,'r1','u1','참가자'),['첫오답','둘째오답']))
        self.assertEqual(sum('오답 1회' in reply for reply in replies),1)
        self.assertEqual(sum('15초 후' in reply for reply in replies),1)
        self.assertIn('누적 오답: 1회',self.send('!퀴즈'))

    def test_unrelated_message_and_failed_start_do_not_consume_quota(self):
        self.assertIsNone(self.send('안녕'))
        with patch.object(self.catalog,'choose',side_effect=ValueError('no question')):
            with self.assertRaises(ValueError):
                self.send('!퀴즈')
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_utc_date_crosses_korean_morning_reset(self):
        from datetime import timezone
        self.send('!퀴즈')
        self.send('!정답 단양')
        self.date=datetime(2026,11,2,18,0,tzinfo=timezone.utc)
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_no_reset_at_midnight_and_reset_at_both_boundaries(self):
        from ship_quiz import quota_period
        self.send('!퀴즈')
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,0,0,tzinfo=KST)
        self.assertIn('2/30',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,2,59,tzinfo=KST)
        self.assertIn('3/30',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,3,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,14,59,tzinfo=KST)
        self.assertIn('2/10',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,15,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))
        self.assertIn('참가자 · 5점',self.send('!퀴즈점수'))
        self.assertEqual(quota_period(datetime(2026,11,3,0,0,tzinfo=KST)),'2026-11-02:15')

    def test_old_daily_state_migrates_without_erasing_used_quota(self):
        state={'day':'2026-11-02','count':10,'active':None,'recent':[20]}
        with sqlite3.connect(self.database) as db:
            db.execute('INSERT INTO rooms VALUES (?,?)',('r1',json.dumps(state)))
        self.assertIn('모두 사용',self.send('!퀴즈'))
        self.date=datetime(2026,11,3,0,0,tzinfo=KST)
        self.assertIn('11/30',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,3,3,0,tzinfo=KST)
        self.assertIn('1/10',self.send('!퀴즈'))

    def test_hot_time_limits_at_exact_boundaries_in_kst(self):
        from ship_quiz import quota_limit
        for day,hour,minute,limit in [(2,15,0,10),(2,17,59,10),(2,18,0,15),
                (2,19,0,15),(2,20,0,20),(2,21,0,20),(2,22,0,25),
                (2,23,0,25),(3,0,0,30),(3,1,0,30),(3,2,59,30),
                (3,3,0,10),(3,14,59,10),(3,15,0,10)]:
            with self.subTest(day=day,hour=hour,minute=minute):
                self.assertEqual(quota_limit(datetime(2026,11,day,hour,minute,tzinfo=KST)),limit)
        from datetime import timezone
        self.assertEqual(quota_limit(datetime(2026,11,2,15,0,tzinfo=timezone.utc)),30)

    def test_unused_fifteen_at_eighteen_then_five_more_at_twenty(self):
        self.date=datetime(2026,11,2,18,0,tzinfo=KST)
        for n in range(1,16):
            self.assertIn(f'{n}/15',self.send('!퀴즈'))
            self.send('!정답 단양')
        exhausted=self.send('!퀴즈')
        self.assertIn('퀴즈 15회를 모두 사용',exhausted)
        self.assertIn('✔️ 핫타임에 5회씩 추가됩니다.\n    (18·20·22·24시에 각 5회 추가)',exhausted)
        self.date=datetime(2026,11,2,19,0,tzinfo=KST)
        self.assertIn('퀴즈 15회를 모두 사용',self.send('!퀴즈'))
        self.date=datetime(2026,11,2,20,0,tzinfo=KST)
        self.assertIn('16/20',self.send('!퀴즈'))
        self.date=datetime(2026,11,3,3,0,tzinfo=KST)
        self.assertIn('16/20',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.assertIn('1/10',self.send('!퀴즈'))
        self.assertIn('참가자 · 16점',self.send('!퀴즈점수'))

    def test_accumulation_without_messages_and_restart_has_no_double_grant(self):
        for _ in range(10):
            self.send('!퀴즈')
            self.send('!정답 단양')
        self.date=datetime(2026,11,2,18,0,tzinfo=KST)
        self.assertIn('11/15',self.send('!퀴즈'))
        self.service=QuizService(self.catalog,self.database,lambda:self.date)
        self.assertIn('11/15',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.date=datetime(2026,11,2,21,0,tzinfo=KST)
        self.assertIn('12/20',self.send('!퀴즈'))
        self.assertIn('1/20',self.send('!퀴즈',room='r2'))

    def test_lower_limit_preserves_existing_progress_and_used_count(self):
        self.date=datetime(2026,11,2,23,0,tzinfo=KST)
        state={'day':'2026-11-02','period':'2026-11-02:15','count':35,'recent':[20],
               'active':dict(question=self.question,number=35,wrong=0,seen=[],limit=40,quota_period='2026-11-02:15')}
        with sqlite3.connect(self.database) as db:
            db.execute('INSERT INTO rooms VALUES (?,?)',('r1',json.dumps(state)))
        self.assertIn('35/35',self.send('!퀴즈'))
        self.send('!정답 단양')
        self.assertIn('퀴즈 25회를 모두 사용',self.send('!퀴즈'))
        self.date=datetime(2026,11,3,3,0,tzinfo=KST)
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

    def test_compact_layout_and_removed_commands_leave_problem_unchanged(self):
        text=self.send('!퀴즈')
        expected='[칸무스 퀴즈 · 1/10]\n\n· 함종: 구축 / 국적: 일본\n· (개2 이상) 화력: 66 / 뇌장: 90\n· 운: 63 (Lv 99 기준)\n\n누적 오답: 0회'
        self.assertEqual(text,expected)
        self.assertIsNone(self.send('!힌트'))
        self.assertIsNone(self.send('!포기'))
        self.assertIn(text,self.send('!퀴즈'))
        import bot
        help_text=bot.COMMANDS['!도움말']
        self.assertIn('!퀴즈 | !정답 | !퀴즈점수',help_text)
        self.assertNotIn('!힌트',help_text)
        self.assertNotIn('!포기',help_text)
        with patch.object(bot.ship_quiz,'service') as service, patch.object(bot.requests,'post') as post:
            for message in ['!힌트','!포기']:
                bot.app.test_client().post('/webhook',json={'msg':message,'json':{'chat_id':'web'}})
            service.assert_not_called()
            post.assert_not_called()


if __name__=='__main__':
    unittest.main()
