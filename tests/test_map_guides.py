import json
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
    def test_codes_do_not_overlap_quest_codes(self):
        for value in ['55','5-5','１－１']:
            self.assertIsNotNone(map_guides.parse_area(value))
        for value in ['B55','2610Bm1','By10','722','5-7','18','イ26']:
            self.assertIsNone(map_guides.parse_area(value))
        self.assertEqual(len(map_guides.AREAS),37)

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
            self.assertIn('루트1 · 중앙(하단)',text)
            self.assertNotIn('원문:',text)
            self.assertNotIn('https://zekamashi.net',text)
            self.assertEqual(guide_lookup.build_preview('55 루트1',root=root),guide_lookup.build_preview('5-5 중앙',root=root))
            text,images=guide_lookup.build_preview('55 중앙',root=root)
            self.assertEqual(len(images),2)
            self.assertIn('게이지 파괴 전',text);self.assertIn('게이지 파괴 후',text)
            self.assertIn('와류',text)
            self.assertEqual(len(guide_lookup.build_preview('55 하단',root=root)[1]),2)
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
            self.assertEqual(text,'1-1 해역 공략\n\n구축4\n【AC】(A:통상 C:보스)\n※ C 진입 70% / B 이탈 30%')
            self.assertEqual(len(pictures),1)
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
