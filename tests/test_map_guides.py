import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import guide_lookup
import map_guides

HTML='''<h1>5-5 サーモン海域北方</h1><div class="entry-content">
<p><img src="/wp-content/uploads/banner.jpg"></p>
<h2>編成例(中央下ルート/ゲージ破壊前)</h2>
<p><img src="/wp-content/uploads/central.jpg"></p>
<p>空母2戦艦2航巡1駆逐1【BKPS】(B:潜水 K:通常 P:通常 S:ボス)</p>
<h2>編成例(中央下ルート/ゲージ破壊後)</h2>
<p><img src="/wp-content/uploads/central-after.jpg"></p>
<p>空母1戦艦2駆逐2補給1【BFDHNOS】(B:対潜 D:渦潮 S:ボス)</p>
<h2>編成例(上ルート)</h2><p><img src="/wp-content/uploads/top.jpg"></p>
<p>戦艦2空母4【BKPS】(S:ボス)</p>
<h2>編成例(下ルート)</h2><p><img src="/wp-content/uploads/bottom.jpg"></p>
<p>戦艦2軽巡1駆逐3【ACEGIMOS】(S:ボス)</p>
<h3>基地航空隊 編成例</h3><p><img src="/wp-content/uploads/air.jpg"></p><p>第一:ボス集中</p>
<details><summary>旧編成</summary><h2>編成例(上ルート)</h2><p>空母6【OLD】</p></details>
<h2>報酬</h2><p><img src="/wp-content/uploads/reward.jpg"></p></div>'''


class MapGuideTests(unittest.TestCase):
    def test_heading_fleet_and_bare_route_do_not_lose_battleships(self):
        html='<h1>5-3 攻略</h1><div class="post-content"><h2>編成例(初攻略) 重巡級5軽巡1</h2><p>編成とルート 【DGIOKEQ】(I:夜戦 K:夜戦 Q:ボス)</p><h2>編成例(初攻略) 低戦1重巡1雷巡1軽巡1駆逐2</h2><p>編成とルート 【DGIOKEQ】(Q:ボス)</p><h2>支援艦隊</h2><h3>具体的な支援編成例</h3><p>駆逐2戦艦3空母1</p></div>'
        record=map_guides.extract(html,'5-3','https://zekamashi.net/kancolle-kouryaku/5-3/')
        variants=[v for r in record['routes'] for v in r['variants']]
        self.assertEqual(len(variants),2)
        self.assertTrue(variants[0]['summary'].startswith('중순급5 경순1'))
        self.assertTrue(variants[1]['summary'].startswith('저속전함1 중순1'))
        self.assertTrue(guide_lookup.translate_route(guide_lookup.find_route('高戦2航巡2駆逐2【AB】')).startswith('고속전함2 항순2'))

    def test_gauge_numbers_are_visible_and_not_merged(self):
        html='<h1>7-3 攻略</h1><div class="post-content"><h2>編成例(1ゲージ目)</h2><p>重巡1駆逐3【AB】</p><h2>編成例(2ゲージ目)</h2><p>重巡1駆逐3【AB】</p></div>'
        record=map_guides.extract(html,'7-3','url')
        self.assertEqual([r['label'] for r in record['routes']],['1게이지','2게이지'])
        self.assertEqual(map_guides.phase_label('第二ゲージ 編成例'),'2게이지')

    def test_first_clear_examples_are_not_confused_with_airbase_examples(self):
        html='<h1>6-5 攻略</h1><div class="post-content"><h2>編成例(下ルート)</h2><p>戦艦2軽巡1駆逐3【BFIJM】</p><img src="/wp-content/uploads/fleet.jpg"><h3>基地航空隊</h3><h4>初めて攻略する際の例(仮置)</h4><img src="/wp-content/uploads/base.jpg"><h2>初攻略にあたって</h2><h3>初攻略での編成案</h3><p>戦艦2軽巡1駆逐3【BFIJM】</p><img src="/wp-content/uploads/first.jpg"></div>'
        record=map_guides.extract(html,'6-5','https://zekamashi.net/kancolle-kouryaku/6-5/')
        self.assertEqual(len(record['routes']),1)
        variants=record['routes'][0]['variants']
        self.assertEqual(len(variants),2)
        self.assertTrue(variants[0]['airbase_images'][0].endswith('base.jpg'))
        self.assertEqual(len(variants[0]['images']),1)
        self.assertTrue(variants[1]['images'][0].endswith('first.jpg'))

    def test_mixed_lower_upper_route_has_its_own_label(self):
        self.assertEqual(map_guides.route_label('編成例(下上ルート)'),'하단→상단')

    def test_offline_reparse_keeps_files_and_marks_missing_images_pending(self):
        from scripts.collect_map_guides import reparse
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'1-1';folder.mkdir()
            html='<h1>1-1 攻略</h1><div class="post-content"><h2>編成例</h2><p>駆逐4【AC】</p><img src="/wp-content/uploads/a.jpg"></div>'
            (folder/'article.html').write_text(html)
            (folder/'a.jpg').write_bytes(b'image')
            (folder/'unused.jpg').write_bytes(b'keep')
            old={'area':'1-1','url':'https://zekamashi.net/kancolle-kouryaku/1-1/',
                 'status':'downloaded','collected_at':'saved',
                 'images':[{'url':'https://zekamashi.net/wp-content/uploads/a.jpg','file':'a.jpg','bytes':5}]}
            path=folder/'manifest.json';path.write_text(json.dumps(old))
            with patch('requests.Session.request',side_effect=AssertionError('No network')):
                self.assertEqual(reparse(['1-1'],Path(tmp)),[])
                self.assertEqual(json.loads(path.read_text())['collected_at'],'saved')
                self.assertEqual((folder/'unused.jpg').read_bytes(),b'keep')
                (folder/'article.html').write_text(html.replace('a.jpg','missing.jpg'))
                self.assertEqual(reparse(['1-1'],Path(tmp)),['1-1'])
                self.assertEqual(json.loads(path.read_text())['status'],'needs_collection')

    def test_reviewed_source_correction_is_bound_to_exact_html(self):
        html='<h1>1-2 攻略</h1><div class="entry-content"><h2>編成例(周回)</h2><p>軽巡1駆逐4【AE】</p></div>'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir()
            correction={'1-2':{'html_sha256':hashlib.sha256(html.encode()).hexdigest(),
                'fleets':[{'heading':'編成例(周回)','original':'경순1 구축4',
                           'replacement':'항순1 구축4','reason':'Reviewed fixture'}]}}
            (root/'data/map_guide_overrides.json').write_text(json.dumps(correction))
            with patch.object(map_guides,'ROOT',root):
                reviewed=map_guides.extract(html,'1-2','url')
                changed=map_guides.extract(html+' ','1-2','url')
            self.assertTrue(reviewed['routes'][0]['variants'][0]['summary'].startswith('항순1 구축4'))
            self.assertTrue(changed['routes'][0]['variants'][0]['summary'].startswith('경순1 구축4'))

    def test_usage_text_and_unknown_quest_match_requested_format(self):
        self.assertEqual(map_guides.USAGE,'사용법: !공략 [임무번호/해역]\n예: !공략 By10 / !공략 By10 65\n     !공략 55 / !공략 55 중앙')
        text,pictures=guide_lookup.build_preview('ㅇ')
        self.assertEqual(text,"'ㅇ' 임무를 찾지 못했습니다.\n"+map_guides.USAGE)
        self.assertEqual(pictures,[])

    def test_same_node_path_is_one_route_with_several_fleets(self):
        html='<h1>1-2 攻略</h1><div class="entry-content"><h2>編成例(周回)</h2><p>航巡1駆逐4【AE】(E:ボス)</p><h2>編成例(初攻略)</h2><p>軽巡1駆逐4【AE】(E:ボス)</p></div>'
        record=map_guides.extract(html,'1-2','https://zekamashi.net/kancolle-kouryaku/1-2/')
        self.assertEqual(len(record['routes']),1)
        self.assertEqual(len(record['routes'][0]['variants']),2)

    def test_fleet_subheadings_keep_alternative_images_and_routes_separate(self):
        html='<h1>1-3 攻略</h1><div class="entry-content"><h2>編成例(周回編成案)</h2><h3>軽空2駆逐4</h3><p><img src="/wp-content/uploads/one.jpg"></p><p>軽空2駆逐4【CFJ】</p><h3>軽空2水母1(3隻)</h3><p><img src="/wp-content/uploads/two.jpg"></p><p>軽空2水母1(3隻)【AEFHJ】</p></div>'
        record=map_guides.extract(html,'1-3','https://zekamashi.net/kancolle-kouryaku/1-3/')
        self.assertEqual(len(record['routes']),2)
        one,two=[r['variants'][0] for r in record['routes']]
        self.assertEqual(len(one['images']),1)
        self.assertTrue(one['images'][0].endswith('one.jpg'))
        self.assertTrue(two['images'][0].endswith('two.jpg'))
        self.assertIn('(3척)',two['summary'])

    def test_reference_images_and_related_article_cards_are_not_fleet_images(self):
        html='<h1>1-5 攻略</h1><div class="entry-content"><h2>編成例</h2><p>駆逐4【ADFGJ】</p><img src="/wp-content/uploads/fleet.jpg"><a class="blogcard__link"><img src="/wp-content/uploads/thumbnail.jpg"></a><h3>対潜条件について(資料)</h3><img src="/wp-content/uploads/battle.jpg"></div>'
        record=map_guides.extract(html,'1-5','https://zekamashi.net/kancolle-kouryaku/1-5/')
        variant=record['routes'][0]['variants'][0]
        self.assertEqual(variant['images'],['https://zekamashi.net/wp-content/uploads/fleet.jpg'])
        self.assertEqual(variant['reference_image_urls'],['https://zekamashi.net/wp-content/uploads/battle.jpg'])

    def test_details_without_any_attributes_are_closed_and_excluded(self):
        html='<h1>3-5 攻略</h1><article class="post-content"><h2>編成例(下ルート)</h2><p>軽巡1駆逐5【FGK】</p><img src="/wp-content/uploads/current.jpg"><details><summary>旧編成</summary><img src="/wp-content/uploads/old.jpg"><p>水母1駆逐5【BCFGK】</p></details></article>'
        record=map_guides.extract(html,'3-5','https://zekamashi.net/kancolle-kouryaku/3-5/')
        variant=record['routes'][0]['variants'][0]
        self.assertEqual(variant['images'],['https://zekamashi.net/wp-content/uploads/current.jpg'])
        self.assertFalse(any('水母1' in n for n in variant['notes_jp']))

    def test_alternative_node_paths_and_boss_probability_are_preserved(self):
        html='<h1>1-3 攻略</h1><div class="entry-content"><h2>編成例(初攻略)</h2><p>軽巡2駆逐4【CFJ】(J:ボス) 【A(DB)EFJ】(E:通常 F:通常 J:ボス) ルート条件 駆逐4以上</p></div>'
        record=map_guides.extract(html,'1-3','https://zekamashi.net/kancolle-kouryaku/1-3/')
        summary=record['routes'][0]['variants'][0]['summary']
        self.assertIn('【CFJ】',summary)
        self.assertIn('【A(DB)EFJ】',summary)
        self.assertEqual(map_guides.translated_branch_notes(['固定なしの例(駆逐2でボス率94%程度)']),['※ 보스 도달률 약 94%'])

    def test_codes_do_not_overlap_quest_codes(self):
        for value in ['55','5-5','１－１']:
            self.assertIsNotNone(map_guides.parse_area(value))
        for value in ['B55','2610Bm1','By10','722','5-7','18','イ26']:
            self.assertIsNone(map_guides.parse_area(value))
        self.assertEqual(len(map_guides.AREAS),37)

    def test_semi_lower_is_not_merged_with_lower(self):
        html='<h1>3-5 攻略</h1><div class="entry-content"><h2>編成例(下ルート)</h2><p>軽巡1駆逐5【FGK】</p><h2>編成例(準下ルート)</h2><p>軽巡2水母4【BCFGK】</p><h2>編成例(上ルート)</h2><p>空母3航巡1潜水2【BDHK】</p></div>'
        record=map_guides.extract(html,'3-5','https://zekamashi.net/kancolle-kouryaku/3-5/')
        self.assertEqual([r['label'] for r in record['routes']],['하단','준하단','상단'])

    def test_visible_examples_group_phases_and_exclude_unrelated_images(self):
        record=map_guides.extract(HTML,'5-5','https://zekamashi.net/kancolle-kouryaku/5-5/')
        self.assertEqual([r['label'] for r in record['routes']],['중앙(하단)','상단','하단'])
        self.assertEqual(len(record['routes'][0]['variants']),2)
        self.assertEqual(record['routes'][0]['variants'][0]['phase'],'게이지 파괴 전')
        images=[x for r in record['routes'] for v in r['variants'] for x in v['images']]
        self.assertEqual(len(images),4)
        self.assertFalse(any('banner' in x or 'reward' in x or 'air.jpg' in x for x in images))
        self.assertEqual(len(record['routes'][2]['variants'][0]['airbase_images']),1)

    def test_overview_and_route_aliases_use_local_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'guide_cache/zekamashi_maps/5-5';folder.mkdir(parents=True)
            record=map_guides.extract(HTML,'5-5','https://zekamashi.net/kancolle-kouryaku/5-5/')
            record['status']='downloaded'
            for r in record['routes']:
                for v in r['variants']:
                    for key in ['images','airbase_images']:
                        names=[]
                        for url in v[key]:
                            name=url.rsplit('/',1)[-1];(folder/name).write_bytes(b'image');names.append(name)
                        v[key]=names
            (folder/'manifest.json').write_text(json.dumps(record),encoding='utf-8')
            text,images=guide_lookup.build_preview('55',root=root)
            self.assertEqual(len(images),3)
            self.assertNotIn('· 제공',text)
            self.assertNotIn('· 색적',text)
            self.assertIn('루트1 · 중앙(하단)',text)
            self.assertNotIn('원문:',text)
            self.assertNotIn('https://zekamashi.net',text)
            self.assertEqual(guide_lookup.build_preview('55 루트1',root=root),guide_lookup.build_preview('5-5 중앙',root=root))
            text,images=guide_lookup.build_preview('55 중앙',root=root)
            self.assertEqual(len(images),2)
            self.assertIn('게이지 파괴 전',text);self.assertIn('게이지 파괴 후',text)
            self.assertIn('와류',text)
            self.assertEqual(len(guide_lookup.build_preview('55 하단',root=root)[1]),2)
            self.assertEqual(len(guide_lookup.build_preview('55 상세',root=root)[1]),5)
            self.assertIn('해당 루트가 없습니다',guide_lookup.build_preview('55 루트99',root=root)[0])

    def test_wrong_area_and_old_articles_fail_closed(self):
        with self.assertRaises(ValueError):map_guides.extract(HTML,'1-1','https://zekamashi.net/kancolle-kouryaku/1-1/')
        with self.assertRaises(ValueError):map_guides.extract(HTML.replace('5-5 サーモン','【一期】5-5 サーモン'),'5-5','url')

    def test_unsaved_map_has_collection_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            text,images=guide_lookup.build_preview('1-1',root=Path(tmp))
            self.assertIn('아직 수집된',text);self.assertFalse(images)

    def test_single_route_has_no_number_selector_or_source_and_shows_probability(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'guide_cache/zekamashi_maps/1-1';folder.mkdir(parents=True)
            record={'area':'1-1','status':'downloaded','url':'https://zekamashi.net/kancolle-kouryaku/1-1/',
                    'routes':[{'number':1,'label':'기본','variants':[{'phase':'',
                    'summary':'구축4 【AC】(A:통상 C:보스)', 'images':['fleet.jpg'],
                    'notes_jp':['※C側に70%。B側に30％で逸れあり']}]}]}
            (folder/'fleet.jpg').write_bytes(b'image')
            (folder/'manifest.json').write_text(json.dumps(record),encoding='utf-8')
            text,pictures=guide_lookup.build_preview('11',root=root)
            self.assertEqual(text,'1-1 해역 공략\n\n구축4\n【AC】(A:통상 C:보스)\n\n상세공략: !공략 11 상세')
            self.assertEqual(len(pictures),1)
            detailed,photos=guide_lookup.build_preview('11 상세',root=root)
            self.assertIn('C 진입 70% / B 이탈 30%',detailed)
            self.assertEqual(photos,pictures)
            for selector in ['루트1','1','기본']:
                self.assertEqual(guide_lookup.build_preview('11 '+selector,root=root),('',[]))

    def test_silent_guide_does_not_send_empty_kakao_message(self):
        import bot
        with patch.object(bot.guide_lookup,'build_preview',return_value=('',[])), \
             patch.object(bot.IMAGE_SEND_EXECUTOR,'submit',side_effect=lambda fn:fn()), \
             patch.object(bot.requests,'post') as post:
            response=bot.app.test_client().post('/webhook',json={'msg':'!공략 11 루트1','json':{'chat_id':'test'}})
            self.assertEqual(response.status_code,200)
            post.assert_not_called()

    def test_probability_translation_does_not_treat_all_routes_as_fixed(self):
        self.assertEqual(map_guides.translated_branch_notes(['※C側に70%。B側に30％で逸れあり']),
                         ['※ C 진입 70% / B 이탈 30%'])
        self.assertEqual(map_guides.translated_branch_notes(['C側に65.5%。B側に34.5%で逸れあり']),
                         ['※ C 진입 65.5% / B 이탈 34.5%'])
        self.assertEqual(map_guides.translated_branch_notes(['制空値70/索敵30']),[])

    def test_explicit_routing_equipment_speed_and_search_requirements(self):
        self.assertEqual(map_guides.translated_branch_notes(['ルート条件 5隻, 駆逐4以上, 高速統一 陣形選択 単縦陣']),['※ 고속통일'])
        self.assertEqual(map_guides.translated_branch_notes(['ルート条件 軽巡1駆逐5, 電探を1つ以上装備 陣形選択 単縦陣']),['※ 전탐 1개 이상'])
        text='ルート条件 ※要索敵。33式分岐点係数1で索敵34以上必要。 ※要 高速統一 。戦艦0 陣形選択 単縦陣'
        self.assertEqual(map_guides.translated_branch_notes([text]),['※ 고속통일 / 색적 34 이상(33식·계수1)'])
        text='ルート条件 ※要索敵。索敵値33式分岐点係数4で40以上必要。陣形選択 単縦陣'
        self.assertEqual(map_guides.translated_branch_notes([text]),['※ 색적 40 이상(33식·계수4)'])
        self.assertEqual(map_guides.translated_branch_notes(['※G→Fの確率が35% Hマスはランダムで経由']),['※ G→F 확률 35% / H 랜덤 경유'])
        self.assertEqual(map_guides.translated_branch_notes(['コメント 高速統一も可能。電探を1つ以上装備']),[])

    def test_collector_resumes_and_keeps_raw_source(self):
        from scripts.collect_map_guides import collect,audit
        calls=[]
        class FakeFetcher:
            def __init__(self,interval):
                self.interval=interval;self.session=SimpleNamespace(headers={'User-Agent':'test'})
                self.robots=None
            def get(self,url):
                calls.append(url)
                if url.endswith('robots.txt'):
                    return SimpleNamespace(text='User-agent: *\nAllow: /',url=url)
                if url.endswith('/5-5/'):
                    return SimpleNamespace(text=HTML,url=url)
                return SimpleNamespace(content=b'image',headers={'Content-Type':'image/jpeg'},url=url)
        with tempfile.TemporaryDirectory() as temp,patch('scripts.collect_map_guides.Fetcher',FakeFetcher):
            output=Path(temp)
            collect(['5-5'],output)
            self.assertEqual((output/'5-5/article.html').read_text(),HTML)
            before=len(calls);collect(['5-5'],output)
            self.assertEqual(len(calls)-before,1) # robots only; no repeated image requests
            record=json.loads((output/'5-5/manifest.json').read_text())
            self.assertEqual(record['status'],'downloaded')
            self.assertEqual(len(record['routes']),3)
            self.assertEqual(next(r for r in audit(output) if r['area']=='5-5')['status'],'downloaded')


if __name__=='__main__':unittest.main()
