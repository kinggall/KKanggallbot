from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import quests
from scripts import build_web,build_pages

ROOT=Path(__file__).resolve().parents[1]

class WebAutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=quests.QuestCatalog(ROOT)
        cls.manifest=json.loads((ROOT/'data/web_guide_links.json').read_text())
        cls.public=json.loads((ROOT/'web/data/quests.json').read_text())

    def test_links_and_export_do_not_read_private_cache(self):
        original=Path.read_text
        def guarded(path,*args,**kwargs):
            if 'guide_cache' in path.parts:raise AssertionError('Private cache must not be read')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',guarded),patch.object(Path,'write_text'),patch.object(build_web.shutil,'copyfile'):
            result=build_web.build(ROOT)
        expected={r['id']:r['guideUrl'] for r in self.public['quests'] if r['guideUrl']}
        self.assertEqual({r['id']:r['guideUrl'] for r in result['quests'] if r['guideUrl']},expected)
        self.assertEqual(len(expected),self.manifest['expected_link_count'])
        build_pages.validate_data(result)

    def load_modified(self,change):
        document=deepcopy(self.manifest);change(document)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/web_guide_links.json').write_text(json.dumps(document))
            return build_web.load_guide_links(root,self.catalog)

    def test_corrupt_links_fail_instead_of_disappearing(self):
        mutations=[lambda d:d['links'][0].update(name_jp='違う任務'),
                   lambda d:d['links'][0].update(id='nonexistent'),
                   lambda d:d['links'][0].update(url='https://evil.example/kancolle-kouryaku/test/'),
                   lambda d:d['links'][0].update(url='http://zekamashi.net/kancolle-kouryaku/test/'),
                   lambda d:d['links'][0].update(url='https://zekamashi.net@evil.example/kancolle-kouryaku/test/'),
                   lambda d:d['links'].pop(),lambda d:d.update(links=[]),
                   lambda d:d['links'].__setitem__(1,deepcopy(d['links'][0]))]
        for change in mutations:
            with self.assertRaises(ValueError):self.load_modified(change)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):build_web.load_guide_links(Path(folder),self.catalog)

    def test_duplicate_keys_codes_and_broken_references_fail(self):
        with self.assertRaises(ValueError):json.loads('{"x":1,"x":2}',object_pairs_hook=build_pages.unique_keys)
        bad=deepcopy(self.public);bad['quests'][1]['code']=bad['quests'][0]['code']
        with self.assertRaises(ValueError):build_pages.validate_data(bad)
        bad=deepcopy(self.public);bad['quests'][0]['before']=['missing']
        with self.assertRaises(ValueError):build_pages.validate_data(bad)
        bad=deepcopy(self.public);bad['search']['bad']=['missing']
        with self.assertRaises(ValueError):build_pages.validate_data(bad)
        bad=deepcopy(self.public);bad['quests'][0]['refresh_token']='test'
        with self.assertRaises(ValueError):build_pages.validate_data(bad)
        bad=deepcopy(self.public);bad['quests'].pop()
        with self.assertRaises(ValueError):build_pages.validate_continuity(self.public,bad)
        build_pages.validate_continuity(self.public,self.public)

    def test_unexpected_public_files_and_credentials_block_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in build_pages.PUBLIC_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            build_pages.validate_directory(root)
            (root/'token.json').write_text('{}')
            with self.assertRaises(ValueError):build_pages.validate_directory(root)
            (root/'token.json').unlink()
            (root/'data/quests.json').write_text('{"refresh_token":"test"}')
            with self.assertRaises(ValueError):build_pages.validate_directory(root)

    def test_public_map_normalization(self):
        self.assertEqual(build_web.sortie_maps({'list':[{'map':['7-2M','7-3P','5-6Z','7-4P']},{'map':['1-1','7-2M']}]}),['7-2-2','7-3-2','5-6-3','7-4','1-1'])
        for row in self.public['quests']:
            self.assertEqual(build_web.sortie_maps(self.catalog.items[row['id']]['requirements']),row['maps'])
