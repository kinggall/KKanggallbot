"""Private Drive data snapshots. Code continues to travel through Git.

PC: bootstrap once, then watch. Cloud: pull, edit, push.
Credentials are read from local token.json or the three proxy secret bindings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile

import requests

DEFAULT_INCLUDES = ['KKanggallbot/guide_cache', 'pictures', 'KKanggallbot/data']
BLOCKED_PARTS = {'.git', '.venv', 'venv', '__pycache__', '.drive-sync', 'logs',
                 'node_modules', '.aws', '.ssh', '.codex'}
BLOCKED_NAMES = {'token.json', 'credentials.json', 'client_secret.json'}
API = 'https://www.googleapis.com/drive/v3/files'
HEAD_NAME = 'kakaobot-data-head.json'


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
            if allowed(rel) and rel not in tracked:
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
            raise RuntimeError(f'Drive request failed: HTTP {response.status_code}')
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

    def upload(self, path, name, existing=None):
        url = 'https://www.googleapis.com/upload/drive/v3/files'
        metadata = {'name': name}
        if existing:
            url += '/' + existing
        else:
            metadata['parents'] = [self.folder]
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


def read_state(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def push(drive, root, state_path, includes, bootstrap=False):
    fid, remote = drive.head()
    state = read_state(state_path)
    if bootstrap and remote:
        raise RuntimeError('Drive already initialized. Use pull; bootstrap cannot overwrite it.')
    if not bootstrap and (not remote or state.get('revision') != remote['revision']):
        raise RuntimeError('Pull the latest cloud snapshot before pushing.')
    files = inventory(root, includes)
    if not files:
        raise RuntimeError('No data files found; nothing uploaded')
    if remote and files == remote['files']:
        print('No data changes.', flush=True)
        return
    revision = uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'data.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, checksum in files.items():
                path = root / name
                z.write(path, name)
                if digest(path) != checksum:
                    raise RuntimeError('A file changed during upload preparation; retry after collection stops')
        archive_id = drive.upload(archive, 'kakaobot-data-' + revision + '.zip')
        # Refuse to publish if another writer advanced the cloud head during upload.
        _, latest = drive.head()
        if (latest or {}).get('revision') != (remote or {}).get('revision'):
            raise RuntimeError('Cloud changed during upload; snapshot retained but not published')
        head = {'revision': revision, 'files': files, 'includes': includes,
                'archive_id': archive_id, 'archive_sha256': digest(archive)}
        doc = Path(tmp) / 'head.json'
        write_json(doc, head)
        drive.upload(doc, HEAD_NAME, fid)
    write_json(state_path, head)
    print(f'Published {len(files)} files. Revision {revision}', flush=True)


def pull(drive, root, state_path):
    _, remote = drive.head()
    if not remote:
        print('Waiting for initial PC bootstrap.', flush=True)
        return
    state = read_state(state_path)
    if state.get('revision') == remote['revision']:
        print('Already current.', flush=True)
        return
    files = remote['files']
    for name in files:
        if not allowed(name):
            raise RuntimeError('Snapshot contains an excluded path')
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Destination escapes sync root')
        if path.exists() and digest(path) not in {files[name], state.get('files', {}).get(name)}:
            raise RuntimeError(f'Local edit conflicts with cloud: {name}. Preserve/review it first.')
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'data.zip'
        response = drive.call('GET', API + '/' + remote['archive_id'],
                              params={'alt': 'media'}, stream=True)
        with response, archive.open('wb') as f:
            for block in response.iter_content(1024 * 1024):
                f.write(block)
        if digest(archive) != remote['archive_sha256']:
            raise RuntimeError('Snapshot checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            if len(z.namelist()) != len(files) or set(z.namelist()) != set(files):
                raise RuntimeError('Archive inventory mismatch')
            staged = Path(tmp) / 'staged'
            for name, checksum in files.items():
                dest = staged / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as source, dest.open('wb') as out:
                    shutil.copyfileobj(source, out)
                if digest(dest) != checksum:
                    raise RuntimeError('File checksum mismatch')
            for name in files:
                dest = root / name
                if dest.exists() and digest(dest) == files[name]:
                    continue
                if dest.exists():
                    backup = state_path.parent / 'backups' / remote['revision'] / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup)
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Same-filesystem atomic replacement; readers never see half a file.
                pending = dest.with_name(dest.name + '.drive-sync-tmp')
                shutil.copy2(staged / name, pending)
                pending.replace(dest)
    # Remote removal does not delete local files in this first version.
    write_json(state_path, remote)
    print(f'Received {len(files)} files. Revision {remote["revision"]}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'bootstrap', 'pull', 'push', 'watch'])
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
    if args.action in {'bootstrap', 'push'}:
        push(drive, root, state, includes, args.action == 'bootstrap')
    elif args.action == 'pull':
        pull(drive, root, state)
    else:
        while True:
            try:
                pull(drive, root, state)
            except (RuntimeError, ValueError, requests.RequestException):
                print('Sync failed or local conflict. Run pull once to inspect; retry later.', flush=True)
            time.sleep(max(30, args.interval))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        # HTTP exceptions may contain credentials: never print their request/response bodies.
        if isinstance(exc, requests.RequestException):
            raise SystemExit('Network request failed; credentials were not logged.')
        raise SystemExit(str(exc))
