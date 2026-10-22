import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quests
import guide_lookup
from scripts.verify_guides import check, markdown, export_metadata


class GuideAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = quests.catalog()
        cls.quest = cls.catalog.items[cls.catalog.by_code['2610b1']]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.folder = self.cache/'2610_B1'
        self.folder.mkdir()
        self.record = {'code':self.quest['wiki_id'],'name_jp':self.quest['name_jp'],
                       'schema_version':2,'status':'downloaded',
                       'url':'https://zekamashi.net/kancolle-kouryaku/example/','images':[]}
        self.make_article(['1-3','1-4','2-1'])

    def make_article(self, maps):
        self.record['images'] = []
        sections = []
        for i, area in enumerate(maps):
            name = f'fleet{i}.jpg'
            url = 'https://zekamashi.net/wp-content/uploads/'+name
            (self.folder/name).write_bytes(b'image')
            self.record['images'].append({'file':name,'url':url,'bytes':5})
            sections.append(f'<h3>{area}</h3><p><img src="{url}"></p>'
                            '<p>軽空2駆逐4【CFJ】(C:通常 F:通常 J:ボス)</p>')
        text = '<h1>'+self.quest['name_jp']+'</h1><div class="entry-content"><h2>編成例</h2>'+''.join(sections)+'</div>'
        (self.folder/'article.html').write_text(text,encoding='utf-8')
        self.write_record()

    def write_record(self):
        (self.folder/'manifest.json').write_text(json.dumps(self.record,ensure_ascii=False),encoding='utf-8')

    def test_all_maps_details_and_photos_ready(self):
        result = check(self.quest,self.cache)
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(result['detail_checks'],3)
        self.assertEqual(result['image_count'],3)

    def test_photo_only_is_served_without_inventing_composition(self):
        path=self.folder/'article.html'
        path.write_text(path.read_text(encoding='utf-8').replace(
            '<p>軽空2駆逐4【CFJ】(C:通常 F:通常 J:ボス)</p>',''),encoding='utf-8')
        result=check(self.quest,self.cache)
        self.assertEqual(result['status'],'ready_images',result)
        text,images=guide_lookup.build_preview('2610B1',cache_root=self.cache)
        self.assertIn('편성은 이미지 참조',text)
        self.assertNotIn('경항모2',text)
        self.assertEqual(len(images),3)

    def test_explicit_fleet_text_without_images_is_usable(self):
        self.record['images']=[]
        self.write_record()
        result=check(self.quest,self.cache)
        self.assertEqual(result['status'],'ready_text',result)
        text,images=guide_lookup.build_preview('2610B1',cache_root=self.cache)
        self.assertIn('경항모2 구축4',text)
        self.assertEqual(images,[])

    def test_repair_reuses_html_search_and_images(self):
        import hashlib
        from scripts import collect_zekamashi as collector
        from unittest.mock import Mock
        root=self.cache/'repo'
        (root/'data').mkdir(parents=True)
        data={'schema':1,'sources':{},'codes':{},'labels':{},'quests':{'new':self.quest}}
        (root/'data/quests.json').write_text(json.dumps(data),encoding='utf-8')
        self.record['status']='review_required'
        self.write_record()
        (self.folder/'search.html').write_text('<a href="'+self.record['url']+'">'+self.quest['name_jp']+'</a>',encoding='utf-8')
        for image in self.record['images']:
            name=hashlib.sha256(image['url'].encode()).hexdigest()[:20]+'.jpg'
            (self.folder/name).write_bytes(b'image')
        fetcher=Mock(interval=10)
        fetcher.session.headers={'User-Agent':'test'}
        def get(url):
            self.assertEqual(url,'https://zekamashi.net/robots.txt')
            return Mock(text='User-agent: *\nAllow: /')
        fetcher.get.side_effect=get
        with patch.object(collector,'ROOT',root),patch.object(collector,'Fetcher',return_value=fetcher), \
                patch('sys.argv',['collector','--repair','--skip-audit','--output',str(self.cache)]):
            collector.main()
        self.assertEqual(fetcher.get.call_count,1)
        updated=json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(updated['status'],'downloaded')
        self.assertEqual(len(updated['images']),3)

    def test_ready_guide_is_listed_in_help(self):
        import bot
        self.assertIn('!공략 [임무번호]',bot.COMMANDS['!도움말'])

    def test_identity_mismatch_not_served(self):
        self.record['code']='B17'
        self.write_record()
        self.assertEqual(check(self.quest,self.cache)['status'],'review')
        text,pictures=guide_lookup.build_preview('2610B1',cache_root=self.cache)
        self.assertEqual(pictures,[])
        self.assertIn('번호·제목',text)

    def test_wrong_article_title_not_served(self):
        path=self.folder/'article.html'
        path.write_text(path.read_text(encoding='utf-8').replace(self.quest['name_jp'],'別の任務'),encoding='utf-8')
        self.assertEqual(check(self.quest,self.cache)['status'],'review')

    def test_error_in_cached_data_gets_webhook_reply(self):
        import bot
        with patch.object(bot.guide_lookup,'build_preview',side_effect=ValueError('bad cache')), \
                patch.object(bot.IMAGE_SEND_EXECUTOR,'submit',side_effect=lambda fn:fn()), \
                patch.object(bot.requests,'post') as post:
            response=bot.app.test_client().post('/webhook',json={
                'msg':'!공략 B100','json':{'chat_id':'audit-room'}})
            self.assertEqual(response.status_code,200)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['json']['room'],'audit-room')
            self.assertIn('공략 자료를 확인하지 못했습니다',post.call_args.kwargs['json']['data'])

    def test_unexpected_map_not_served(self):
        self.make_article(['6-1'])
        result=check(self.quest,self.cache)
        self.assertEqual(result['status'],'review')
        self.assertIn('6-1',result['reason'])
        self.assertEqual(guide_lookup.build_preview('2610B1',cache_root=self.cache)[1],[])

    def test_partial_is_explicit(self):
        self.make_article(['1-3'])
        self.assertEqual(check(self.quest,self.cache)['status'],'partial')
        text,pictures=guide_lookup.build_preview('2610B1',cache_root=self.cache)
        self.assertIn('1-4/2-1 공략 연결은 확인 중',text)
        self.assertTrue(pictures)

    def test_missing_photo_and_metadata_only(self):
        (self.folder/'fleet0.jpg').unlink()
        self.assertEqual(check(self.quest,self.cache)['status'],'incomplete')
        self.assertEqual(check(self.quest,self.cache,True)['status'],'metadata_only')

    def test_empty_photo_is_incomplete(self):
        (self.folder/'fleet0.jpg').write_bytes(b'')
        self.assertEqual(check(self.quest,self.cache)['status'],'incomplete')

    def test_missing_and_no_match_and_malformed_json(self):
        self.record['status']='no_match_on_first_page'
        self.write_record()
        self.assertEqual(check(self.quest,self.cache)['status'],'no_match')
        (self.folder/'manifest.json').write_text('{',encoding='utf-8')
        self.assertEqual(check(self.quest,self.cache)['status'],'incomplete')
        (self.folder/'manifest.json').unlink()
        self.assertEqual(check(self.quest,self.cache)['status'],'missing')

    def test_report_and_export_preserve_folders_without_photos(self):
        self.record['status']='no_match_on_first_page'
        self.write_record()
        report={'checked_at':'test','metadata_only':False,'quests':[check(self.quest,self.cache)]}
        text=markdown(report)
        self.assertIn('2610 B1',text)
        self.assertIn('공략 부재 확정 아님',text)
        output=self.cache/'export.zip'
        export_metadata(self.cache,output)
        import zipfile
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(set(archive.namelist()),{'2610_B1/manifest.json','2610_B1/article.html'})
