import json
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
        allowed={'index.html','style.css','navigation.css','app.js','_headers','data/quests.json','LICENSE','THIRD_PARTY_NOTICES.md'}
        self.assertEqual({p.relative_to(ROOT/'web').as_posix() for p in (ROOT/'web').rglob('*') if p.is_file()},allowed)
        for row in self.data['quests']:
            if row['guideUrl']:
                parsed=urlparse(row['guideUrl'])
                self.assertEqual((parsed.scheme,parsed.hostname),('https','zekamashi.net'))
                self.assertTrue(parsed.path.startswith('/kancolle-kouryaku/'))
        text=(ROOT/'web/data/quests.json').read_text(encoding='utf-8')
        for marker in ['refresh_token','client_secret','127.0.0.1','C:\\KakaoBot','/workspace/','<script','<img']:
            self.assertNotIn(marker,text)
