import hashlib
import subprocess
import tempfile
from pathlib import Path
import unittest
import importlib.util

_spec = importlib.util.spec_from_file_location('stockbot_drive_test_support', Path(__file__).resolve().parents[1] / 'tests/test_drive_sync.py')
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
FakeDrive, sync = _support.FakeDrive, _support.sync

class StockbotSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.cloud=self.base/'cloud';self.pc=self.base/'pc'
        self.repo=self.cloud/'KKanggallbot';(self.repo/'stockbot').mkdir(parents=True)
        self.pc.mkdir();self.remote=self.base/'origin.git'
        self.run_git(self.repo,'init','-b','main')
        self.run_git(self.repo,'config','user.email','test@example.invalid')
        self.run_git(self.repo,'config','user.name','Sync test')
        (self.repo/'stockbot/main.py').write_text('version = 1\n')
        self.run_git(self.repo,'add','stockbot');self.run_git(self.repo,'commit','-m','first')
        self.first=self.run_git(self.repo,'rev-parse','HEAD')
        self.run_git(self.base,'clone','--bare',str(self.repo),str(self.remote))
        self.run_git(self.repo,'remote','add','origin',str(self.remote))
        self.run_git(self.base,'clone',str(self.remote),str(self.pc/'KKanggallbot'))
        self.drive=FakeDrive();self.includes=['KKanggallbot/stockbot']

    def run_git(self,path,*args):
        return subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True,text=True).stdout.strip()

    def release(self):
        (self.repo/'stockbot/main.py').write_text('version = 2\n')
        (self.repo/'stockbot/__init__.py').write_text('# package\n')
        self.run_git(self.repo,'add','stockbot');self.run_git(self.repo,'commit','-m','stock update')
        self.run_git(self.repo,'push','origin','main')
        return self.run_git(self.repo,'rev-parse','HEAD')

    def publish(self):
        sync.push(self.drive,self.cloud,self.cloud/'.drive-sync/state.json',self.includes,True)

    def test_github_drive_pc_package_roundtrip_stays_git_clean(self):
        revision=self.release();self.publish()
        self.assertEqual(self.drive.current['schema'],3)
        self.assertEqual(self.drive.current['stockbot_commit'],revision)
        self.assertEqual(len(self.drive.current['files']),2)
        sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')
        self.assertEqual((self.pc/'KKanggallbot/stockbot/main.py').read_text(),'version = 2\n')
        self.assertEqual(self.run_git(self.pc/'KKanggallbot','rev-parse','HEAD'),revision)
        self.assertEqual(self.run_git(self.pc/'KKanggallbot','status','--porcelain'),'')
        count=len(self.drive.downloads)
        sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')
        self.assertEqual(len(self.drive.downloads),count)

    def test_bad_drive_bytes_do_not_advance_pc_git(self):
        self.release();self.publish()
        item=self.drive.current['files']['KKanggallbot/stockbot/main.py']
        self.drive.objects[item['id']]=b'bad code'
        with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):
            sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')
        self.assertEqual(self.run_git(self.pc/'KKanggallbot','rev-parse','HEAD'),self.first)

    def test_changed_manifest_or_pc_edits_are_not_overwritten(self):
        self.release();self.publish()
        path=self.pc/'KKanggallbot/stockbot/main.py';path.write_text('my local edit\n')
        with self.assertRaisesRegex(RuntimeError,'Local stockbot edits'):
            sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')
        self.assertEqual(path.read_text(),'my local edit\n')
        self.drive.current['files']['KKanggallbot/stockbot/main.py']['sha256']=hashlib.sha256(b'bad').hexdigest()
        with self.assertRaisesRegex(RuntimeError,'differs from GitHub'):
            sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')

    def test_older_drive_release_does_not_roll_back_newer_git(self):
        self.publish();revision=self.release()
        pc_repo=self.pc/'KKanggallbot'
        self.run_git(pc_repo,'fetch','origin','main');self.run_git(pc_repo,'merge','--ff-only',revision)
        sync.pull(self.drive,self.pc,self.pc/'.drive-sync/state.json')
        self.assertEqual(self.run_git(pc_repo,'rev-parse','HEAD'),revision)
        self.assertEqual((pc_repo/'stockbot/main.py').read_text(),'version = 2\n')

    def test_only_committed_code_is_included(self):
        for name in ['token.json','.env','session.db','untracked.py']:
            (self.repo/'stockbot'/name).write_text('private')
        self.assertEqual(set(sync.inventory(self.cloud,self.includes)),{'KKanggallbot/stockbot/main.py'})
        (self.repo/'stockbot/main.py').write_text('uncommitted')
        with self.assertRaisesRegex(RuntimeError,'Commit stockbot changes'):
            sync.inventory(self.cloud,self.includes)

    def test_narrow_fetch_refspec_reproduces_stale_tracking_reference(self):
        pc_repo=self.pc/'KKanggallbot'
        self.run_git(pc_repo,'config','--replace-all','remote.origin.fetch','+HEAD:refs/remotes/origin/HEAD')
        revision=self.release();self.run_git(pc_repo,'fetch','origin','main')
        self.assertEqual(self.run_git(pc_repo,'rev-parse','origin/main'),self.first)
        self.assertEqual(self.run_git(pc_repo,'rev-parse','FETCH_HEAD'),revision)
        watcher=(Path(__file__).resolve().parents[1]/'watch_bot.ps1').read_text()
        self.assertIn('rev-parse --verify FETCH_HEAD',watcher)
        self.assertNotIn('rev-parse "origin/$Branch"',watcher)
        self.assertIn('Local code updated by sync.',watcher)

    def test_unpushed_commit_is_not_published_to_drive(self):
        (self.repo/'stockbot/main.py').write_text('version = 3\n')
        self.run_git(self.repo,'add','stockbot');self.run_git(self.repo,'commit','-m','not pushed')
        with self.assertRaisesRegex(RuntimeError,'Push stockbot commit to GitHub'):
            self.publish()
        self.assertIsNone(self.drive.current)
