import json
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import urlparse
import quests

ROOT=Path(__file__).resolve().parents[1]

class PublicWebExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'web/data/quests.json').read_text(encoding='utf-8'))
        cls.catalog=quests.catalog()

    def test_google_verification_tag_is_in_static_html_head(self):
        class MetaParser(HTMLParser):
            in_head=False
            values=[]
            def handle_starttag(self,tag,attrs):
                if tag=='head': self.in_head=True
                attributes=dict(attrs)
                if tag=='meta' and self.in_head and attributes.get('name')=='google-site-verification':
                    self.values.append(attributes.get('content'))
            def handle_endtag(self,tag):
                if tag=='head': self.in_head=False
        parser=MetaParser()
        parser.feed((ROOT/'web/index.html').read_text(encoding='utf-8'))
        self.assertEqual(parser.values,['w5wlBP9_Tr3GfutbOTsvySRRIB2qvtBJwd-SGm5O2n0'])

    def test_public_rows_match_bot_details(self):
        self.assertEqual(len(self.data['quests']),len(self.catalog.items))
        for row in self.data['quests']:
            source=self.catalog.items[row['id']]
            self.assertEqual(row['title'],source['name_ko'])
            self.assertEqual(row['detail'],self.catalog.detail(row['id']))
            self.assertEqual(set(row),{'id','code','aliases','title','titleJp','category','frequency','frequencyLabel','ended','limited','releaseDate','isNew','detail','maps','guideUrl','before','after'})

    def test_search_aliases_match_bot(self):
        for query in ['뽀이','베이','6구','수상반격','나구모']:
            needle=quests.normalized(query)
            title_matches={k for k,r in self.catalog.items.items() if needle not in self.data['unitQueries'] and not r.get('unavailable') and any(needle in quests.normalized(r.get(f,'')) for f in ['name_ko','name_jp'])}
            actual=set(self.data['search'].get(needle,[]))|title_matches
            self.assertEqual(actual,set(self.catalog.search_keys(query)),query)

    def test_public_directory_has_no_cache_or_credentials(self):
        allowed={'index.html','privacy.html','privacy.css','style.css','navigation.css','app.js','_headers','data/quests.json','LICENSE','THIRD_PARTY_NOTICES.md'}
        self.assertEqual({p.relative_to(ROOT/'web').as_posix() for p in (ROOT/'web').rglob('*') if p.is_file()},allowed)
        for row in self.data['quests']:
            if row['guideUrl']:
                parsed=urlparse(row['guideUrl'])
                self.assertEqual((parsed.scheme,parsed.hostname),('https','zekamashi.net'))
                self.assertTrue(parsed.path.startswith('/kancolle-kouryaku/'))
        text=(ROOT/'web/data/quests.json').read_text(encoding='utf-8')
        for marker in ['refresh_token','client_secret','127.0.0.1','C:\\KakaoBot','/workspace/','<script','<img']:
            self.assertNotIn(marker,text)

    def test_public_privacy_policy_is_linked_and_available_without_login_or_script(self):
        policy=(ROOT/'web/privacy.html').read_text(encoding='utf-8')
        home=(ROOT/'web/index.html').read_text(encoding='utf-8')
        self.assertIn('href="privacy.html"',home)
        self.assertIn('Google Drive 연동 도구',home)
        self.assertIn('<h1>개인정보처리방침</h1>',policy)
        for section in ('처리하는 정보','Google Drive 권한','보관 기간','공유와 외부 서비스',
                        '보호 조치','접근권한 철회','Limited Use','kinggall','2026년 11월 5일'):
            self.assertIn(section,policy)
        self.assertIn('https://www.googleapis.com/auth/drive',policy)
        self.assertIn('https://myaccount.google.com/connections',policy)
        self.assertIn('https://developers.google.com/terms/api-services-user-data-policy',policy)
        self.assertNotIn('<script',policy)
        self.assertNotIn('<iframe',policy)
        self.assertNotIn('gmail.com',policy)

    def test_privacy_local_links_resolve_to_public_assets(self):
        class LinkParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links=[]
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                for field in ('href','src'):
                    if values.get(field): self.links.append(values[field])
        parser=LinkParser()
        parser.feed((ROOT/'web/privacy.html').read_text(encoding='utf-8'))
        for link in parser.links:
            parsed=urlparse(link)
            if parsed.scheme or parsed.netloc or link.startswith('#'):
                continue
            path=parsed.path
            if path=='./': path='index.html'
            self.assertTrue((ROOT/'web'/path).is_file(),link)
