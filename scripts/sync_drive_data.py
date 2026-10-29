"""Private Drive individual-file sync. Code continues to travel through Git.

PC: bootstrap once, then watch. Cloud: pull, edit, push.
Credentials are read from local token.json or the three proxy secret bindings.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

DEFAULT_INCLUDES = ['KKanggallbot/guide_cache', 'pictures', 'KKanggallbot/data',
                    'KakaoBot_사용방법.txt', 'KKanggallbot/stockbot']
BLOCKED_PARTS = {'.git', '.venv', 'venv', '__pycache__', '.drive-sync', 'logs',
                 'node_modules', '.aws', '.ssh', '.codex'}
BLOCKED_NAMES = {'token.json', 'credentials.json', 'client_secret.json'}
API = 'https://www.googleapis.com/drive/v3/files'
HEAD_NAME = 'kakaobot-data-head.json'
STOCK_PREFIX = 'KKanggallbot/stockbot/'

def stock_code(name):
    return name.startswith(STOCK_PREFIX) and PurePosixPath(name).suffix == '.py' and allowed(name)

def git(root, *arguments, check=True):
    return subprocess.run(['git', '-C', str(Path(root)/'KKanggallbot'), *arguments],
                          capture_output=True, check=check, timeout=60)


class GitSyncError(RuntimeError):
    """Controlled Git diagnostic without provider output or credential URLs."""


def fetch_main(root):
    # FETCH_HEAD is shared mutable state: another watcher can truncate it.
    # Each fetch owns a private ref and does not read or write FETCH_HEAD.
    ref = 'refs/kakaobot/drive-sync/' + uuid.uuid4().hex
    try:
        result = git(root, 'fetch', '--quiet', '--no-write-fetch-head', 'origin',
                     '+refs/heads/main:' + ref, check=False)
        if result.returncode:
            raise GitSyncError('Git fetch failed (exit ' + str(result.returncode) + '); retry later.')
        result = git(root, 'rev-parse', '--verify', ref + '^{commit}', check=False)
        revision = result.stdout.decode('ascii', errors='ignore').strip()
        if result.returncode or len(revision) not in (40, 64) or any(c not in '0123456789abcdef' for c in revision):
            raise GitSyncError('Git fetched revision unavailable; retry later.')
        return revision
    except (subprocess.SubprocessError, OSError):
        raise GitSyncError('Git unavailable or timed out; retry later.') from None
    finally:
        try:
            git(root, 'update-ref', '-d', ref, check=False)
        except (subprocess.SubprocessError, OSError):
            pass  # An unused temporary ref is safer than deleting other refs.

def git_hash(root, revision, name):
    blob=git(root,'show',revision+':'+name.removeprefix('KKanggallbot/'),check=False)
    return hashlib.sha256(blob.stdout).hexdigest() if blob.returncode==0 else None


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe relative path')
    return p


def allowed(name):
    p = safe_relative(name)
    lower = [x.lower() for x in p.parts]
    return not (set(lower) & BLOCKED_PARTS or lower[-1] in BLOCKED_NAMES
                or lower[-1].startswith(('.env', 'client_secret'))
                or p.suffix.lower() in {'.har', '.pem', '.key', '.pfx', '.exe', '.dll'})


def inventory(root, includes):
    tracked = set()
    repo = root / 'KKanggallbot'
    if (repo / '.git').exists():
        result = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z'],
                                capture_output=True, check=True)
        tracked = {'KKanggallbot/' + n for n in result.stdout.decode().split('\0') if n}
    found = {}
    for name in includes:
        relative = safe_relative(name)
        base = root.joinpath(*relative.parts)
        if not base.exists():
            continue
        for path in ([base] if base.is_file() else base.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Path escapes sync root')
            rel = path.relative_to(root).as_posix()
            if rel.startswith(STOCK_PREFIX):
                if rel not in tracked or not stock_code(rel):continue
                if digest(path)!=git_hash(root,'HEAD',rel):
                    raise RuntimeError('Commit stockbot changes before publishing: '+rel)
                found[rel]=digest(path)
            elif allowed(rel) and rel not in tracked:
                found[rel] = digest(path)
    return found


class Drive:
    def __init__(self, folder, token_file):
        self.folder = folder
        if token_file:
            values = json.loads(Path(token_file).read_text(encoding='utf-8-sig'))
        else:
            values = {k: os.environ.get('GOOGLE_DRIVE_' + k.upper())
                      for k in ('refresh_token', 'client_id', 'client_secret')}
        if not all(values.get(k) for k in ('refresh_token', 'client_id', 'client_secret')):
            raise ValueError('Missing OAuth settings; use --token-file on the PC')
        self.values = values
        self.session = requests.Session()
        self.deadline = 0

    def call(self, method, url, **kwargs):
        if time.monotonic() >= self.deadline:
            response = requests.post('https://oauth2.googleapis.com/token', data={
                k: self.values[k] for k in ('refresh_token', 'client_id', 'client_secret')
            } | {'grant_type': 'refresh_token'}, timeout=45)
            if not response.ok:
                raise RuntimeError(f'Google authentication failed: HTTP {response.status_code}')
            token = response.json()
            self.session.headers['Authorization'] = 'Bearer ' + token['access_token']
            self.deadline = time.monotonic() + max(1, token.get('expires_in', 3600) - 120)
        response = self.session.request(method, url, timeout=180, **kwargs)
        if not response.ok:
            reasons=[]
            try:
                for item in response.json().get('error',{}).get('errors',[]):
                    reason=item.get('reason','')
                    if reason and reason.replace('_','').isalnum():reasons.append(reason)
            except (ValueError,AttributeError,TypeError):
                pass
            detail=' ('+', '.join(reasons)+')' if reasons else ''
            raise RuntimeError(f'Drive request failed: HTTP {response.status_code}'+detail)
        return response

    def head(self):
        response = self.call('GET', API, params={
            'q': f"'{self.folder}' in parents and trashed=false and name='{HEAD_NAME}'",
            'fields': 'files(id)', 'pageSize': 100}).json()['files']
        if len(response) > 1:
            raise RuntimeError('Duplicate sync heads; manual review required')
        if not response:
            return None, None
        fid = response[0]['id']
        return fid, self.call('GET', API + '/' + fid, params={'alt': 'media'}).json()

    def upload(self, path, name, existing=None, parent=None):
        url = 'https://www.googleapis.com/upload/drive/v3/files'
        metadata = {'name': name}
        if existing:
            url += '/' + existing
        else:
            metadata['parents'] = [parent or self.folder]
        if path.stat().st_size<=5*1024*1024:
            # Ordinary guide files need only one request. Avoid a separate
            # resumable-session handshake for small HTML/JSON/image payloads.
            boundary='kakaobot_'+uuid.uuid4().hex
            content=path.read_bytes()
            mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            body=(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                  +json.dumps(metadata,ensure_ascii=False).encode()+b'\r\n'
                  +f'--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()
                  +content+f'\r\n--{boundary}--\r\n'.encode())
            result=self.call('PATCH' if existing else 'POST',url,
                             params={'uploadType':'multipart','fields':'id,md5Checksum'},
                             data=body,headers={'Content-Type':f'multipart/related; boundary={boundary}'}).json()
            if result.get('md5Checksum') and result['md5Checksum']!=hashlib.md5(content).hexdigest():
                raise RuntimeError('Drive upload checksum mismatch')
            return result['id']
        location = self.call('PATCH' if existing else 'POST', url,
                             params={'uploadType': 'resumable'}, json=metadata,
                             headers={'X-Upload-Content-Type': 'application/octet-stream'}).headers['Location']
        # Do not forward credentials to an unexpected resumable-upload host.
        from urllib.parse import urlsplit
        target = urlsplit(location)
        if target.scheme != 'https' or target.hostname != 'www.googleapis.com':
            raise RuntimeError('Unexpected upload destination')
        with path.open('rb') as f:
            return self.call('PUT', location, data=f,
                             headers={'Content-Type': 'application/octet-stream'}).json()['id']

    def children(self, parent):
        result, page = [], None
        while True:
            params = {'q': f"'{parent}' in parents and trashed=false",
                      'fields': 'nextPageToken,files(id,name,mimeType,size,md5Checksum)',
                      'pageSize': 1000}
            if page:
                params['pageToken'] = page
            data = self.call('GET', API, params=params).json()
            result.extend(data.get('files', []))
            page = data.get('nextPageToken')
            if not page:
                return result

    def create_folder(self, name, parent):
        return self.call('POST', API, json={'name': name, 'parents': [parent],
                         'mimeType': 'application/vnd.google-apps.folder'},
                         params={'fields': 'id'}).json()['id']


def read_state(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}




def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def md5(path):
    h = hashlib.md5()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tree(drive, includes):
    """List only selected data subtrees, never the whole user's Drive."""
    folders = {'': drive.folder}
    files = {}
    for include in includes:
        parent, parts = drive.folder, []
        include_parts = safe_relative(include).parts
        is_file = False
        for index, part in enumerate(include_parts):
            parts.append(part)
            path = '/'.join(parts)
            if path in folders:
                parent = folders[path]
                continue
            matches = [f for f in drive.children(parent) if f['name'] == part]
            if len(matches) == 1 and index == len(include_parts) - 1 and matches[0]['mimeType'] != 'application/vnd.google-apps.folder':
                files[path] = matches[0]
                is_file = True
                break
            if len(matches) != 1 or matches[0]['mimeType'] != 'application/vnd.google-apps.folder':
                raise RuntimeError('Missing or duplicate data folder: ' + path)
            parent = folders[path] = matches[0]['id']
        if is_file:
            continue
        pending = [(include, parent)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            while pending:
                results = list(pool.map(lambda item: (item[0], drive.children(item[1])), pending))
                pending = []
                for prefix, children in results:
                    for item in children:
                        path = prefix + '/' + item['name']
                        if not allowed(path):
                            continue
                        if item['mimeType'] == 'application/vnd.google-apps.folder':
                            # Browser uploads can leave duplicate folders. Traverse
                            # both; accept duplicate files only if their content agrees.
                            folders.setdefault(path, item['id'])
                            pending.append((path, item['id']))
                        else:
                            prior = files.get(path)
                            if prior and (not item.get('md5Checksum') or
                                          prior.get('md5Checksum') != item['md5Checksum'] or
                                          prior.get('size') != item.get('size')):
                                raise RuntimeError('Different duplicate data files: ' + path)
                            if prior:
                                continue
                            files[path] = item
    return files, folders


def publish_index(drive, head_id, head, state_path):
    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / 'head.json'
        write_json(doc, head)
        drive.upload(doc, HEAD_NAME, head_id)
    write_json(state_path, head)


def adopt(drive, root, state_path, includes):
    """Verify browser-uploaded files, then retire ZIP references without deletion."""
    head_id, previous = drive.head()
    local = inventory(root, includes)
    if not local:
        raise RuntimeError('No local reference data to verify')
    remote, folders = tree(drive, includes)
    indexed = {}
    for i, (name, checksum) in enumerate(local.items(), 1):
        item = remote.get(name)
        if not item or item.get('md5Checksum') != md5(root / name):
            raise RuntimeError('Missing or different uploaded file: ' + name)
        indexed[name] = {'id': item['id'], 'sha256': checksum,
                         'md5': item['md5Checksum'], 'bytes': int(item['size'])}
        if i % 200 == 0:
            print(f'Verified {i}/{len(local)} individual files', flush=True)
    _, latest = drive.head()
    if (latest or {}).get('revision') != (previous or {}).get('revision'):
        raise RuntimeError('Drive index changed during verification')
    head = {'schema': 2, 'revision': uuid.uuid4().hex, 'files': indexed,
            'includes': includes, 'folders': folders}
    # Keep the previous index locally for rollback, but never depend on its ZIP.
    if previous:
        write_json(state_path.parent / 'before-individual-files.json', previous)
    publish_index(drive, head_id, head, state_path)
    print(f'Individual-file mode enabled: {len(indexed)} verified files. ZIP no longer required.', flush=True)


def checksum(entry):
    return entry.get('sha256') if isinstance(entry, dict) else entry


def push(drive, root, state_path, includes, bootstrap=False):
    head_id, remote = drive.head()
    state = read_state(state_path)
    if bootstrap and remote:
        raise RuntimeError('Drive already initialized. Use adopt-files for existing folders.')
    if not bootstrap and (not remote or remote.get('schema') not in (2,3) or
                          state.get('revision') != remote['revision']):
        raise RuntimeError('Pull the latest individual-file index before pushing.')
    files = inventory(root, includes)
    if not files:
        raise RuntimeError('No data files found')
    indexed = dict((remote or {}).get('files', {}))
    publishing_stock = 'KKanggallbot/stockbot' in includes and any(stock_code(n) for n in files)
    stock_commit = git(root,'rev-parse','HEAD').stdout.decode().strip() if publishing_stock else (remote or {}).get('stockbot_commit')
    if publishing_stock:
        fetched = fetch_main(root)
        if git(root,'merge-base','--is-ancestor',stock_commit,fetched,check=False).returncode:
            raise RuntimeError('Push stockbot commit to GitHub main before Drive sync')
        previous=(remote or {}).get('stockbot_commit')
        if previous and git(root,'merge-base','--is-ancestor',previous,stock_commit,check=False).returncode:
            raise RuntimeError('Older stockbot checkout cannot replace a newer Drive release')
    removed_stock = [n for n in indexed if stock_code(n) and publishing_stock and n not in files]
    for name in removed_stock:del indexed[name]
    folders = dict((remote or {}).get('folders', {'': drive.folder}))
    changed = [n for n, h in files.items() if checksum(indexed.get(n)) != h]
    if not changed and not removed_stock and stock_commit == (remote or {}).get('stockbot_commit'):
        print('No data changes. Uploaded 0 files.', flush=True)
        return
    for i, name in enumerate(changed, 1):
        path = root / name
        prior = indexed.get(name)
        if prior:
            metadata = drive.call('GET', API + '/' + prior['id'],
                                  params={'fields': 'md5Checksum'}).json()
            if metadata.get('md5Checksum') != prior['md5']:
                # Recover an upload that finished before a prior process could
                # publish its index. Never replace different external content.
                current_md5 = md5(path)
                if metadata.get('md5Checksum') != current_md5:
                    raise RuntimeError('File was edited directly in Drive: ' + name)
                indexed[name] = {'id': prior['id'], 'sha256': files[name],
                                 'md5': current_md5, 'bytes': path.stat().st_size}
                print(f'Verified prior upload {i}/{len(changed)}: {name}', flush=True)
                continue
        parent, parts = drive.folder, []
        for part in PurePosixPath(name).parts[:-1]:
            parts.append(part)
            key = '/'.join(parts)
            if key not in folders:
                matches = [f for f in drive.children(parent) if f['name'] == part]
                if len(matches) > 1 or (matches and matches[0]['mimeType'] != 'application/vnd.google-apps.folder'):
                    raise RuntimeError('Duplicate or non-folder parent: ' + key)
                folders[key] = matches[0]['id'] if matches else drive.create_folder(part, parent)
            parent = folders[key]
        if not prior:
            existing=[f for f in drive.children(parent) if f['name']==path.name]
            if existing:
                # A prior run may have uploaded a new file before a gateway
                # failure prevented publishing the index. Reuse exact content.
                current_md5=md5(path)
                if (len(existing)!=1 or existing[0].get('md5Checksum')!=current_md5
                        or int(existing[0].get('size',-1))!=path.stat().st_size):
                    raise RuntimeError('Unindexed Drive file already exists; review before overwriting: ' + name)
                indexed[name]={'id':existing[0]['id'],'sha256':files[name],
                               'md5':current_md5,'bytes':path.stat().st_size}
                print(f'Verified prior upload {i}/{len(changed)}: {name}',flush=True)
                continue
        fid = drive.upload(path, path.name, prior['id'] if prior else None, parent=parent)
        if digest(path) != files[name]:
            raise RuntimeError('Local file changed during transfer: ' + name)
        indexed[name] = {'id': fid, 'sha256': files[name], 'md5': md5(path), 'bytes': path.stat().st_size}
        print(f'Uploaded {i}/{len(changed)}: {name}', flush=True)
    _, latest = drive.head()
    if (latest or {}).get('revision') != (remote or {}).get('revision'):
        raise RuntimeError('Another publisher changed the index; review before continuing')
    head = {'schema': 3 if stock_commit else 2, 'revision': uuid.uuid4().hex, 'files': indexed,
            'includes': includes, 'folders': folders}
    if stock_commit:head['stockbot_commit']=stock_commit
    publish_index(drive, head_id, head, state_path)
    print(f'Published {len(changed)} changed files. No ZIP created.', flush=True)


def stock_sync_plan(root, remote):
    names=[n for n in remote['files'] if n.startswith(STOCK_PREFIX)]
    if not names:return None
    if any(not stock_code(n) for n in names):raise RuntimeError('Non-code or excluded stockbot file in index')
    target=remote.get('stockbot_commit','')
    if remote.get('schema')!=3 or len(target)!=40 or any(c not in '0123456789abcdef' for c in target):
        raise RuntimeError('Missing stockbot Git release identity')
    fetched = fetch_main(root)
    if git(root,'merge-base','--is-ancestor',target,fetched,check=False).returncode:
        raise RuntimeError('Drive stockbot commit is not in GitHub main')
    expected={'KKanggallbot/'+n for n in git(root,'ls-tree','-r','--name-only',target,'--','stockbot').stdout.decode().splitlines()
              if stock_code('KKanggallbot/'+n)}
    if expected!=set(names):raise RuntimeError('Incomplete stockbot package in Drive release')
    for name in names:
        if git_hash(root,target,name)!=remote['files'][name]['sha256']:
            raise RuntimeError('Drive stockbot code differs from GitHub commit: '+name)
    current=git(root,'rev-parse','HEAD').stdout.decode().strip()
    if git(root,'diff','--quiet','HEAD','--','stockbot',check=False).returncode:
        raise RuntimeError('Local stockbot edits detected; not overwriting')
    if git(root,'merge-base','--is-ancestor',target,current,check=False).returncode==0:
        return {'skip':set(names),'advance':False}
    if git(root,'merge-base','--is-ancestor',current,target,check=False).returncode:
        raise RuntimeError('PC Git history diverged; manual review required')
    if git(root,'diff','--quiet','HEAD',check=False).returncode:
        raise RuntimeError('Local Git edits detected; not updating stockbot release')
    return {'skip':set(),'advance':True,'current':current,'target':target,'names':names}


def pull(drive, root, state_path):
    _, remote = drive.head()
    if not remote:
        print('Waiting for initial data index.', flush=True)
        return
    if remote.get('schema') not in (2,3):
        raise RuntimeError('ZIP index found. Run adopt-files in the cloud before starting file sync.')
    state = read_state(state_path)
    code_plan=stock_sync_plan(root,remote)
    changed = []
    observed = {}
    for name, item in remote['files'].items():
        if not allowed(name):
            raise RuntimeError('Excluded file in index')
        if code_plan and name in code_plan['skip']:continue
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Destination escapes sync root')
        actual = digest(path) if path.exists() else None
        if actual == item['sha256']:
            continue
        prior = git_hash(root,'HEAD',name) if stock_code(name) else checksum(state.get('files', {}).get(name))
        if actual is not None and actual != prior:
            raise RuntimeError('Local edit conflicts with cloud: ' + name)
        changed.append(name)
        observed[name] = actual
    with tempfile.TemporaryDirectory() as temp:
        staged = Path(temp)
        for i, name in enumerate(changed, 1):
            item = remote['files'][name]
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            response = drive.call('GET', API + '/' + item['id'], params={'alt': 'media'}, stream=True)
            with response, target.open('wb') as f:
                for block in response.iter_content(1024 * 1024):
                    f.write(block)
            if digest(target) != item['sha256']:
                raise RuntimeError('File checksum mismatch: ' + name)
            print(f'Downloaded {i}/{len(changed)}: {name}', flush=True)
        # Verify every changed file before replacing any existing file.
        for name in changed:
            dest = root / name
            actual = digest(dest) if dest.exists() else None
            if actual != observed[name]:
                raise RuntimeError('Local file changed during download: ' + name)
        if code_plan and code_plan['advance']:
            if git(root,'rev-parse','HEAD').stdout.decode().strip()!=code_plan['current']:
                raise RuntimeError('PC Git version changed during sync; retry without overwriting')
            if git(root,'merge','--ff-only',code_plan['target'],check=False).returncode:
                raise RuntimeError('Cannot fast-forward PC to stockbot release; local files preserved')
            print('Installed Drive-verified Git release: '+code_plan['target'][:7],flush=True)
        for name in changed:
            if stock_code(name):continue  # Git installed the verified bytes and index together.
            dest = root / name
            if dest.exists():
                backup = state_path.parent / 'backups' / remote['revision'] / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pending = dest.with_name(dest.name + '.drive-sync-tmp')
            shutil.copy2(staged / name, pending)
            pending.replace(dest)
    write_json(state_path, remote)
    print(f'Synced {len(changed)} changed files. ZIP downloads: 0.', flush=True)


def watch(drive, root, state, interval):
    while True:
        try:
            pull(drive, root, state)
        except GitSyncError as exc:
            print(str(exc), flush=True)
        except subprocess.SubprocessError as exc:
            # CalledProcessError/TimeoutExpired may include secrets in command,
            # stdout or stderr. Only emit their controlled category/exit code.
            code = exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 'timeout'
            print(f'Git operation failed ({code}). Sync will retry; no forced overwrite.', flush=True)
        except OSError:
            print('Local file or process unavailable. Sync will retry; no forced overwrite.', flush=True)
        except (RuntimeError, ValueError, requests.RequestException):
            print('Sync failed or local conflict. Run pull once to inspect; retry later.', flush=True)
        time.sleep(max(30, interval))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'bootstrap', 'adopt-files', 'pull', 'push', 'watch'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--folder', default=os.environ.get('GOOGLE_DRIVE_FOLDER_ID',
                                                        '14ShSbg3jMRQtm2ffpkYq2sEI8rd-e6-i'))
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--include', action='append', help='Relative data path; repeat as needed')
    parser.add_argument('--interval', type=int, default=120)
    args = parser.parse_args()
    root = args.root.resolve()
    includes = args.include or DEFAULT_INCLUDES
    if args.action == 'plan':
        files = inventory(root, includes)
        print(json.dumps({'root': str(root), 'files': len(files),
                          'bytes': sum((root / n).stat().st_size for n in files),
                          'includes': includes, 'paths': sorted(files)}, ensure_ascii=False, indent=2))
        return
    state = root / '.drive-sync' / 'state.json'
    drive = Drive(args.folder, args.token_file)
    if args.action == 'adopt-files':
        adopt(drive, root, state, includes)
    elif args.action in {'bootstrap', 'push'}:
        push(drive, root, state, includes, args.action == 'bootstrap')
    elif args.action == 'pull':
        pull(drive, root, state)
    else:
        watch(drive, root, state, args.interval)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, requests.RequestException, subprocess.SubprocessError, OSError) as exc:
        # HTTP exceptions may contain credentials: never print their request/response bodies.
        if isinstance(exc, requests.RequestException):
            raise SystemExit('Network request failed; credentials were not logged.')
        if isinstance(exc, subprocess.SubprocessError):
            raise SystemExit('Git operation failed or timed out; credentials were not logged.')
        if isinstance(exc, OSError):
            raise SystemExit('Local file or process unavailable; existing files were not forcibly overwritten.')
        raise SystemExit(str(exc))
