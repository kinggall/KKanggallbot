import unittest
from scripts.collect_maintenance_oembed import collect, extract_oembed, post_id


def embed(pid, text, date='November 24, 2026', author='KanColle_STAFF'):
    return {'author_url':'https://twitter.com/'+author,
            'url':'https://x.com/'+author+'/status/'+pid,
            'html':f'<blockquote><p>{text}</p><a href="https://x.com/{author}/status/{pid}">{date}</a></blockquote>'}


class OEmbedTests(unittest.TestCase):
    def test_official_embed_date_and_quote_chain_include_unnumbered_seed(self):
        data={'100':embed('100','Completed <a href="https://t.co/latest">quote</a>'),
              '102':embed('102','02▼Second <a href="https://t.co/first">quote</a>'),
              '101':embed('101','01▼First')}
        links={'https://t.co/latest':'https://twitter.com/KanColle_STAFF/status/102',
               'https://t.co/first':'https://x.com/KanColle_STAFF/status/101'}
        result=collect(data.__getitem__,links.__getitem__,['https://x.com/KanColle_STAFF/status/100'],'2026-11-24',2)
        self.assertEqual([p['number'] for p in result['posts']],[1,2])
        self.assertEqual(result['missing_numbers'],[])

    def test_missing_numbers_and_ellipsis_remain_explicit(self):
        result=collect(lambda pid:embed(pid,'02▼Second…'),lambda _:None,
                       ['https://x.com/KanColle_STAFF/status/102'],'2026-11-24',2)
        self.assertEqual(result['missing_numbers'],[1])
        self.assertEqual(result['possibly_truncated_numbers'],[2])

    def test_foreign_authors_or_mismatched_post_ids_are_rejected(self):
        with self.assertRaises(ValueError):extract_oembed(embed('101','01▼Fake',author='other'),'101')
        with self.assertRaises(ValueError):extract_oembed(embed('102','01▼Fake'),'101')
        for url in ('http://x.com/KanColle_STAFF/status/1','https://example.com/KanColle_STAFF/status/1',
                    'https://x.com/other/status/1'):
            with self.assertRaises(ValueError):post_id(url)

    def test_old_dates_are_not_mixed_and_external_redirects_are_not_requested(self):
        old=collect(lambda pid:embed(pid,'01▼Old','November 11, 2026'),lambda _:None,
                    ['https://x.com/KanColle_STAFF/status/101'],'2026-11-24',1)
        self.assertEqual(old['posts'],[])
        data=embed('101','01▼Current <a href="https://t.co/image">image</a>')
        called=[]
        def fetch(pid):called.append(pid);return data
        result=collect(fetch,lambda _:'https://example.com/KanColle_STAFF/status/2',
                       ['https://x.com/KanColle_STAFF/status/101'],'2026-11-24',2)
        self.assertEqual(called,['101'])
        self.assertEqual(result['missing_numbers'],[2])

    def test_duplicate_numbers_are_not_silently_overwritten(self):
        data={'101':embed('101','01▼First <a href="https://x.com/KanColle_STAFF/status/102">next</a>'),
              '102':embed('102','01▼Conflict')}
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            collect(data.__getitem__,lambda _:None,['https://x.com/KanColle_STAFF/status/101'],'2026-11-24',3)
