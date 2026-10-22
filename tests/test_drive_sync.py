import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('drive_sync', Path(__file__).resolve().parents[1] / 'scripts/sync_drive_data.py')
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class Response:
    def __init__(self, data):
        self.data = data

    def iter_content(self, size):
        yield self.data

    def json(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeDrive:
    def __init__(self):
        self.objects = {}
        self.current = None
        self.folder = 'root'
        self.nodes = {}
        self.downloads = []
        self.uploads = []

    def head(self):
        return ('head', self.current) if self.current else (None, None)

    def upload(self, path, name, existing=None, parent=None):
        fid = existing or str(len(self.nodes))
        self.objects[fid] = path.read_bytes()
        self.nodes[fid] = {'id':fid, 'name':name, 'parent':parent or self.folder,
                          'mimeType':'application/octet-stream', 'size':str(path.stat().st_size),
                          'md5Checksum':hashlib.md5(path.read_bytes()).hexdigest()}
        self.uploads.append(name)
        if name == sync.HEAD_NAME:
            self.current = json.loads(self.objects[fid])
        return fid

    def call(self, method, url, **kwargs):
        fid = url.rsplit('/', 1)[-1]
        if kwargs.get('params', {}).get('alt') == 'media':
            self.downloads.append(fid)
            return Response(self.objects[fid])
        return Response(self.nodes[fid])

    def children(self, parent):
        return [n for n in self.nodes.values() if n['parent'] == parent]

    def create_folder(self, name, parent):
        fid = str(len(self.nodes))
        self.nodes[fid] = {'id':fid,'name':name,'parent':parent,
                          'mimeType':'application/vnd.google-apps.folder'}
        return fid


class SyncTests(unittest.TestCase):
    def test_root_instruction_file_roundtrip_and_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pc=root/'pc';cloud=root/'cloud';pc.mkdir()
            name='KakaoBot_사용방법.txt'
            (pc/name).write_text('재부팅 후 실행 순서',encoding='utf-8')
            d=FakeDrive()
            sync.push(d,pc,pc/'.drive-sync/state.json',[name],True)
            files,_=sync.tree(d,[name])
            self.assertEqual(set(files),{name})
            sync.pull(d,cloud,cloud/'.drive-sync/state.json')
            self.assertEqual((cloud/name).read_text(encoding='utf-8'),'재부팅 후 실행 순서')

    def test_roundtrip_conflict_backup_and_stale_push(self):
        with tempfile.TemporaryDirectory() as temp:
            pc, cloud = Path(temp) / 'pc', Path(temp) / 'cloud'
            original = pc / 'pictures/kinggall.png'
            original.parent.mkdir(parents=True)
            original.write_bytes(b'first')
            drive = FakeDrive()
            ps, cs = pc / '.drive-sync/state.json', cloud / '.drive-sync/state.json'
            sync.push(drive, pc, ps, ['pictures'], bootstrap=True)
            sync.pull(drive, cloud, cs)
            target = cloud / 'pictures/kinggall.png'
            self.assertEqual(target.read_bytes(), b'first')
            target.write_bytes(b'cloud-edit')
            sync.push(drive, cloud, cs, ['pictures'])
            with self.assertRaisesRegex(RuntimeError, 'Pull the latest'):
                sync.push(drive, pc, ps, ['pictures'])
            original.write_bytes(b'local-conflict')
            with self.assertRaisesRegex(RuntimeError, 'Local edit conflicts'):
                sync.pull(drive, pc, ps)
            self.assertEqual(original.read_bytes(), b'local-conflict')
            original.write_bytes(b'first')
            sync.pull(drive, pc, ps)
            self.assertEqual(original.read_bytes(), b'cloud-edit')
            backups = list((pc / '.drive-sync/backups').rglob('*.png'))
            self.assertEqual(backups[0].read_bytes(), b'first')
            with self.assertRaisesRegex(RuntimeError, 'already initialized'):
                sync.push(drive, pc, ps, ['pictures'], bootstrap=True)
            self.assertFalse(any(name.endswith('.zip') for name in drive.uploads))
            before = len(drive.downloads)
            sync.pull(drive, pc, ps)
            self.assertEqual(len(drive.downloads), before)

    def test_sensitive_files_and_symlinks_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'pictures').mkdir()
            for name in ['token.json', 'credentials.json', '.env', 'test.har', 'valid.png']:
                (root / 'pictures' / name).write_bytes(b'x')
            (root / 'pictures/link.png').symlink_to(root / 'pictures/valid.png')
            self.assertEqual(set(sync.inventory(root, ['pictures'])), {'pictures/valid.png'})

    def test_unsafe_paths(self):
        for path in ['../escape', '/absolute', 'C:/secret', 'pictures\\bad']:
            with self.assertRaises(ValueError):
                sync.safe_relative(path)

    def test_bad_file_does_not_change_local_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drive = FakeDrive()
            drive.current = {'schema':2, 'revision':'r', 'files':{
                'pictures/a.png':{'id':'blob','sha256':'wrong'}}}
            drive.objects['blob'] = b'broken file'
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                sync.pull(drive, root, root / '.drive-sync/state.json')
            self.assertFalse((root / 'pictures/a.png').exists())

    def test_only_changed_file_transferred_and_external_edits_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            pc, cloud = Path(temp)/'pc', Path(temp)/'cloud'
            (pc/'pictures').mkdir(parents=True)
            for name in ['a.png','b.png']:
                (pc/'pictures'/name).write_bytes(name.encode())
            d=FakeDrive(); ps=pc/'.drive-sync/state.json';cs=cloud/'.drive-sync/state.json'
            sync.push(d,pc,ps,['pictures'],True)
            sync.pull(d,cloud,cs)
            d.uploads.clear();d.downloads.clear()
            (cloud/'pictures/a.png').write_bytes(b'changed')
            sync.push(d,cloud,cs,['pictures'])
            self.assertEqual(d.uploads,['a.png',sync.HEAD_NAME])
            sync.pull(d,pc,ps)
            self.assertEqual(len(d.downloads),1)
            fid=d.current['files']['pictures/a.png']['id']
            d.nodes[fid]['md5Checksum']='external change'
            (cloud/'pictures/a.png').write_bytes(b'next')
            with self.assertRaisesRegex(RuntimeError,'edited directly'):
                sync.push(d,cloud,cs,['pictures'])

    def test_adopt_existing_files_does_not_upload_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pictures').mkdir()
            p=root/'pictures/a.png';p.write_bytes(b'photo')
            d=FakeDrive();folder=d.create_folder('pictures','root')
            d.upload(p,'a.png',parent=folder);d.uploads.clear()
            sync.adopt(d,root,root/'.drive-sync/state.json',['pictures'])
            self.assertEqual(d.uploads,[sync.HEAD_NAME])
            self.assertEqual(d.current['schema'],2)
            self.assertNotIn('archive_id',d.current)

    def test_duplicate_folders_accept_only_identical_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pictures').mkdir()
            p=root/'pictures/a.png';p.write_bytes(b'photo')
            d=FakeDrive();parent=d.create_folder('pictures','root')
            one=d.create_folder('nested',parent);two=d.create_folder('nested',parent)
            d.upload(p,'a.png',parent=one);other=d.upload(p,'a.png',parent=two)
            files,_=sync.tree(d,['pictures'])
            self.assertEqual(len(files),1)
            d.nodes[other]['md5Checksum']='different'
            with self.assertRaisesRegex(RuntimeError,'Different duplicate'):
                sync.tree(d,['pictures'])

    def test_legacy_state_migrates_without_download_and_recreates_missing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pictures').mkdir()
            p=root/'pictures/a.png';p.write_bytes(b'photo')
            d=FakeDrive();parent=d.create_folder('pictures','root')
            d.upload(p,'a.png',parent=parent)
            legacy={'revision':'zip-old','files':{'pictures/a.png':sync.digest(p)},'archive_id':'deleted-zip'}
            state=root/'.drive-sync/state.json';sync.write_json(state,legacy)
            d.current=legacy
            sync.adopt(d,root,state,['pictures'])
            # An old PC state may still point at a ZIP which no longer exists.
            sync.write_json(state,legacy)
            sync.pull(d,root,state)
            self.assertEqual(d.downloads,[])
            p.unlink()
            sync.pull(d,root,state)
            self.assertEqual(len(d.downloads),1)
            self.assertEqual(p.read_bytes(),b'photo')

    def test_upload_interrupted_before_index_can_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pictures').mkdir()
            p=root/'pictures/a.png';p.write_bytes(b'old')
            d=FakeDrive();state=root/'.drive-sync/state.json'
            sync.push(d,root,state,['pictures'],True)
            fid=d.current['files']['pictures/a.png']['id']
            p.write_bytes(b'new');d.upload(p,'a.png',existing=fid)
            sync.push(d,root,state,['pictures'])
            self.assertEqual(d.current['files']['pictures/a.png']['sha256'],sync.digest(p))

    def test_edit_during_download_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pictures').mkdir()
            p=root/'pictures/a.png';p.write_bytes(b'old')
            d=FakeDrive();state=root/'.drive-sync/state.json'
            sync.push(d,root,state,['pictures'],True)
            fid=d.current['files']['pictures/a.png']['id']
            d.objects[fid]=b'new'
            d.current['files']['pictures/a.png']['sha256']=hashlib.sha256(b'new').hexdigest()
            original=d.call
            def edit(method,url,**kwargs):
                response=original(method,url,**kwargs)
                p.write_bytes(b'edited while downloading')
                return response
            d.call=edit
            with self.assertRaisesRegex(RuntimeError,'changed during download'):
                sync.pull(d,root,state)
            self.assertEqual(p.read_bytes(),b'edited while downloading')


if __name__ == '__main__':
    unittest.main()
