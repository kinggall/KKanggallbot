import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import guide_lookup
import quests
import quest_guide_comments as comments


class QuestGuideCommentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.catalog=quests.catalog()

    def quest(self,code):return self.catalog.items[self.catalog.by_code[code.casefold()]]

    def save_comments(self,code,html,**extra):
        folder=self.root/'guide_cache/guide_audit';folder.mkdir(parents=True,exist_ok=True)
        entry={'html_sha256':hashlib.sha256(html.encode()).hexdigest(),**extra}
        (folder/'quest_guide_comments.json').write_text(json.dumps({'quests':{code:entry}}))

    def save_guide(self,code,body):
        quest=self.quest(code);html=f'<h1>{quest["name_jp"]}</h1><div class="entry-content">{body}</div>'
        folder=self.root/'guide_cache/zekamashi'/code;folder.mkdir(parents=True)
        (folder/'article.html').write_text(html)
        (folder/'fleet.jpg').write_bytes(b'image')
        record={'code':code,'name_jp':quest['name_jp'],'status':'downloaded','schema_version':2,
                'url':'https://zekamashi.net/kancolle-kouryaku/test/',
                'images':[{'file':'fleet.jpg','url':'https://zekamashi.net/wp-content/uploads/fleet.jpg','bytes':5}]}
        (folder/'manifest.json').write_text(json.dumps(record))
        return html

    def add_general(self,area):
        folder=self.root/'guide_cache/zekamashi_maps'/area;folder.mkdir(parents=True)
        (folder/'fleet.jpg').write_bytes(b'image')
        variant={'phase':'','source_heading':'general','summary':'경순1 구축5 【AB】(B:보스)',
                 'images':['fleet.jpg'],'airbase_images':[],'notes_jp':[]}
        (folder/'manifest.json').write_text(json.dumps({'area':area,'status':'downloaded',
            'routes':[{'number':1,'label':'기본','variants':[variant]}]}))

    def test_term_rules_do_not_turn_negative_or_support_types_into_other_advice(self):
        html='<div class="entry-content"><h2>編成例</h2><h3>5-5</h3><p>道中支援を採用します。</p><p>対空カットインは不要です。</p><p>渦潮を回避します。</p></div>'
        facts=comments.source_facts(html,self.quest('By10'))
        self.assertTrue(any('도중지원' in f['ko'] for f in facts))
        self.assertFalse(any('결전지원' in f['ko'] or '대공 컷인' in f['ko'] or '와류' in f['ko'] for f in facts))
        self.assertEqual(facts[0]['maps'],['5-5'])

    def test_no_source_produces_condition_summary_without_inventing_comments(self):
        lines=comments.notes(self.quest('B77'),self.root)
        self.assertTrue(2<=len(lines)<=3)
        self.assertIn('2-2/2-3',' '.join(lines))
        self.assertNotIn('원문',' '.join(lines))

    def test_source_hash_and_area_scope_control_which_facts_are_displayed(self):
        quest=self.quest('By10');html='saved HTML'
        facts=[{'maps':['5-5'],'ko':'도중 경로 메모'},{'maps':['6-4'],'ko':'육상 보스 메모'}]
        self.save_comments('By10',html,facts=facts)
        lines=comments.notes(quest,self.root,area='5-5',source_html=html)
        self.assertIn('목표: 5-5 보스 S승 2회',lines)
        self.assertIn('도중 경로 메모',lines);self.assertNotIn('육상 보스 메모',lines)
        self.assertNotIn('도중 경로 메모',comments.notes(quest,self.root,source_html='changed'))
        self.assertNotIn('도중 경로 메모',comments.notes(quest,self.root,source_html=html,allow_source=False))

    def test_b101_uses_reviewed_comments_not_old_photos_or_numbers(self):
        html=self.save_guide('B101','<p>※現在一期の内容になっています。</p><h2>編成例</h2><p>制空220</p>')
        self.save_comments('B101',html,text_only=True,facts=[
            {'maps':['4-5'],'ko':'쿠마노 기함·스즈야 2번함을 유지합니다.'},
            {'maps':['4-5'],'ko':'현행 수치는 !공략 45를 참고합니다.'},
            {'maps':['6-2'],'ko':'자유칸에 따른 경로와 색적을 확인합니다.'}])
        for area in ['4-5','6-2']:self.add_general(area)
        diagnostics={};text,images=guide_lookup.build_preview('B101',root=self.root,diagnostics=diagnostics)
        self.assertEqual(images,[]);self.assertTrue(diagnostics['commentary_only'])
        self.assertEqual(diagnostics['missing_maps'],[])
        self.assertNotIn('220',text);self.assertIn('쿠마노 기함',text)
        self.assertIn('해당해역: 4-5 / 6-2',text)
        detail,_=guide_lookup.build_preview('B101 45',root=self.root)
        self.assertIn('목표: 4-5 보스 S승 1회',detail)

    def test_retired_b101_photos_are_not_sent_before_private_data_sync(self):
        self.save_guide('B101','<p>※現在一期の内容になっています。</p><h2>編成例</h2>')
        folder=self.root/'data';folder.mkdir()
        (folder/'quest_guide_comment_overrides.json').write_text(json.dumps({'B101':{'text_only':True}}))
        text,images=guide_lookup.build_preview('B101',root=self.root)
        self.assertEqual(images,[]);self.assertIn('사진 없이 코멘트',text)

    def test_b103_keeps_23_image_and_resolves_51_as_general_guide(self):
        html=self.save_guide('B103','<h2>編成例</h2><h3>2-3</h3><p><img src="https://zekamashi.net/wp-content/uploads/fleet.jpg"></p><p>軽空2駆逐4【BEFJN】(N:ボス)</p><h3>5-1</h3><p>編成例が一期内容のため消去しています。</p>')
        self.save_comments('B103',html,general_only_maps=['5-1'],facts=[{'maps':['5-1'],'ko':'2기 전용 편성이 없어 일반 공략을 참고합니다.'}])
        self.add_general('5-1')
        text,images=guide_lookup.build_preview('B103',root=self.root)
        self.assertEqual(len(images),1)
        self.assertIn('예: !공략 51',text)
        self.assertIn('5-1은 2기 전용 편성이 없어',text)
        self.assertNotIn('5-1 공략 연결은 확인 중',text)
        detail,images=guide_lookup.build_preview('B103 51',root=self.root)
        self.assertEqual(images,[]);self.assertIn('예: !공략 51',detail)


if __name__=='__main__':unittest.main()
