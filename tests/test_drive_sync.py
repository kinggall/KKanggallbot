import importlib.util
import json
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

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeDrive:
    def __init__(self):
        self.objects = {}
        self.current = None

    def head(self):
        return ('head', self.current) if self.current else (None, None)

    def upload(self, path, name, existing=None):
        fid = existing or str(len(self.objects))
        self.objects[fid] = path.read_bytes()
        if name == sync.HEAD_NAME:
            self.current = json.loads(self.objects[fid])
        return fid

    def call(self, method, url, **kwargs):
        return Response(self.objects[url.rsplit('/', 1)[-1]])


class SyncTests(unittest.TestCase):
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

    def test_bad_archive_does_not_change_local_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drive = FakeDrive()
            drive.current = {'revision': 'r', 'files': {'pictures/a.png': 'checksum'},
                             'archive_id': 'blob', 'archive_sha256': 'wrong'}
            drive.objects['blob'] = b'broken zip'
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                sync.pull(drive, root, root / '.drive-sync/state.json')
            self.assertFalse((root / 'pictures/a.png').exists())


if __name__ == '__main__':
    unittest.main()
