"""Room-selected photos for members and the bot; no unscoped lookup or disk cache."""
import base64
import re
import threading
import time
import unicodedata
from urllib.parse import urljoin, urlsplit

import requests

ROOM_ID = '18182686594126049'
ROOM_IDS = {
    ROOM_ID,                # 칸코레 진수부에 어서오세요
    '18250420501835535',     # 왕갤의 둥지
    '18335522977842954',     # 니나브귀여워
}
MAX_BYTES = 8 * 1024 * 1024
SLOTS = threading.BoundedSemaphore(2)


class ProfileError(ValueError):
    pass


def nickname(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()


def checked_url(value):
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower()
        if (parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443)
                or not any(host == domain or host.endswith('.' + domain) for domain in ('kakaocdn.net', 'kakao.com'))):
            raise ValueError
    except (ValueError, TypeError):
        raise ProfileError('프로필 사진 주소를 확인할 수 없습니다.') from None
    return value


def image_bytes(data):
    return (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')
            or data[:6] in (b'GIF87a', b'GIF89a')
            or data[:4] == b'RIFF' and data[8:12] == b'WEBP')


class ProfileService:
    def __init__(self, get=requests.get, post=requests.post, clock=time.monotonic):
        self.get, self.post, self.clock = get, post, clock
        self.lock, self.next_requests = threading.Lock(), {}

    def reserve(self, room=ROOM_ID):
        with self.lock:
            now = self.clock()
            if now < self.next_requests.get(str(room), 0):
                return False
            self.next_requests[str(room)] = now + 3
            return True

    def room_rows(self, base, room, uid=None):
        query = ('SELECT m.user_id, m.nickname, m.profile_image_url, m.enc '
                 'FROM db2.open_chat_member m JOIN db1.chat_rooms c ON c.link_id = m.link_id '
                 'WHERE c.id = ?')
        bind = [str(room)]
        if uid is not None:
            query += ' AND m.user_id = ?'
            bind.append(str(uid))
        query += ' ORDER BY m._id DESC' + (' LIMIT 1' if uid is not None else '')
        response = self.post(base + '/query', json={'query': query, 'bind': bind}, timeout=(2, 5))
        response.raise_for_status()
        document = response.json()
        rows = document.get('data') if isinstance(document, dict) and not document.get('error') else None
        if not isinstance(rows, list):
            raise ProfileError('이 방의 참가자 정보를 조회하지 못했습니다.')
        return rows

    def room_bot_profile(self, base, room, uid):
        """The logged-in account's selected profile, linked to this room only.

        open_profile has no enc/_id columns. Its actual full/original field
        names differ from open_chat_member (confirmed on the user's device).
        """
        response = self.post(base + '/query', json={
            'query': ('SELECT c.id AS room_id, p.user_id, p.nickname, p.profile_type, p.link_member_type, '
                      'p.profile_image_url, p.f_profile_image_url AS full_profile_image_url, '
                      'p.o_profile_image_url AS original_profile_image_url '
                      'FROM db2.open_profile p JOIN db1.chat_rooms c ON c.link_id = p.link_id '
                      'WHERE c.id = ? AND p.user_id = ?'),
            'bind': [str(room), str(uid)]}, timeout=(2, 5))
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict) or document.get('error'):
            return None  # Older schema: keep the existing member lookup.
        rows = document.get('data')
        if not isinstance(rows, list):
            return None
        verified = [r for r in rows if isinstance(r, dict)
                    and str(r.get('room_id')) == str(room) and str(r.get('user_id')) == str(uid)]
        if len(verified) > 1:
            raise ProfileError('이 방에 선택된 봇 프로필이 여러 개라 사진을 선택할 수 없습니다.')
        if not verified:
            return None
        return {**verified[0], '_profile_source': 'open_profile'}

    def bot_member(self, name, base, room, members):
        """Configured bot label is an alias only for this room's proven self ID."""
        try:
            response = self.get(base + '/config', timeout=(2, 3))
            response.raise_for_status()
            document = response.json()
            if isinstance(document, dict) and document.get('error'):
                return None
            config = document.get('payload', document) if isinstance(document, dict) else None
            if not isinstance(config, dict):
                return None
            uid = str(config.get('bot_id', ''))
            if not uid.isdecimal() or int(uid) == 0:
                return None
            requested_alias = nickname(config.get('bot_name')) == nickname(name)
            try:
                selected = self.room_bot_profile(base, room, uid)
            except ProfileError:
                if requested_alias:
                    raise
                return None
            except requests.RequestException:
                selected = None
            if selected is not None:
                return selected if requested_alias or nickname(selected.get('nickname')) == nickname(name) else None
            if not requested_alias:
                return None
            own = next((m for m in members if str(m.get('user_id') or m.get('id')) == uid), None)
            if own is None:
                rows = self.room_rows(base, room, uid)
                own = next((m for m in rows if isinstance(m, dict) and str(m.get('user_id')) == uid), None)
            if own and nickname(own.get('nickname') or own.get('name')):
                return own
            raise ProfileError('이 방에 선택된 봇 프로필을 Iris에서 확인하지 못했습니다.')
        except (requests.RequestException, TypeError, ValueError) as error:
            if isinstance(error, ProfileError):
                raise
            return None

    def photo_candidates(self, name, reply_url, room=ROOM_ID):
        base = reply_url.rsplit('/', 1)[0]
        response = self.get(f'{base}/room/{room}/members', timeout=(2, 5))
        legacy = response.status_code == 404
        if legacy:
            # Older Iris: constrain the encrypted member query to this room's
            # link_id. Never fall back to /user or a normal friends profile.
            rows = self.room_rows(base, room)
        else:
            response.raise_for_status()
            document = response.json()
            if isinstance(document, dict) and document.get('error'):
                raise ProfileError('이 방의 참가자 정보를 조회하지 못했습니다.')
            payload = document.get('payload', document) if isinstance(document, dict) else None
            rows = payload.get('members') if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProfileError('이 방의 참가자 정보를 조회하지 못했습니다.')
        # The endpoint can be capped at 256 rows. On a miss, re-read the same
        # room rather than treating an incomplete API list as authoritative.
        if not legacy and not any(isinstance(r, dict) and nickname(r.get('nickname') or r.get('name')) == nickname(name) for r in rows):
            try:
                refreshed = self.room_rows(base, room)
                if refreshed:
                    rows = refreshed
            except (requests.RequestException, ValueError, TypeError):
                pass
        # Iris returns newest records first; one result per member identity.
        unique = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            key = str(row.get('user_id') or row.get('id') or 'row:' + str(index))
            unique.setdefault(key, row)
        matches = [r for r in unique.values() if nickname(r.get('nickname') or r.get('name')) == nickname(name)]
        if not matches:
            own = self.bot_member(name, base, room, unique.values())
            if own:
                matches = [own]
        if not matches:
            partial = [r for r in unique.values() if nickname(name) in nickname(r.get('nickname') or r.get('name'))]
            if len(partial) == 1:
                matches = partial
        if not matches:
            candidates = []
            for row in unique.values():
                full_name = row.get('nickname') or row.get('name')
                if isinstance(full_name, str) and nickname(name) in nickname(full_name) and full_name not in candidates:
                    candidates.append(full_name)
            if candidates:
                lines = ['[닉네임 검색]', '아래 명령어를 복사해 다시 입력해 주세요.']
                if len(candidates) > 20:
                    lines += ['검색 결과가 많습니다. 닉네임을 더 길게 입력해 주세요.']
                lines += ['', *('!프사 ' + full_name for full_name in candidates[:20])]
                raise ProfileError('\n'.join(lines))
            raise ProfileError('해당 닉네임을 조회된 방 참가자 목록에서 찾지 못했습니다. 정확한 닉네임을 입력해 주세요.')
        if len(matches) != 1:
            raise ProfileError('같은 닉네임의 참가자가 여러 명이라 사진을 선택할 수 없습니다.')
        member = matches[0]
        matched_name = member.get('nickname') or member.get('name')
        fields = ('original_profile_image_url', 'full_profile_image_url', 'profile_image_url')
        addresses = {field: member.get(field) for field in fields}
        uid = str(member.get('user_id') or member.get('id') or '')
        # The members API normally exposes only the thumbnail. Ask the same
        # room's OpenChat record for optional high-resolution columns. Older
        # schemas may lack one or both columns; never query friends or /user.
        if uid.isdecimal() and member.get('_profile_source') != 'open_profile':
            for field in fields[:2]:
                if addresses[field]:
                    continue
                try:
                    result = self.post(base + '/query', json={
                        'query': f'SELECT m.user_id, m.nickname, m.{field}, m.enc FROM db2.open_chat_member m JOIN db1.chat_rooms c ON c.link_id = m.link_id WHERE c.id = ? AND m.user_id = ? ORDER BY m._id DESC LIMIT 1',
                        'bind': [str(room), uid]}, timeout=(2, 3))
                    result.raise_for_status()
                    document = result.json()
                    rows = document.get('data') if isinstance(document, dict) and not document.get('error') else None
                    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
                        row = rows[0]
                        if str(row.get('user_id')) == uid and nickname(row.get('nickname')) == nickname(matched_name):
                            addresses[field] = row.get(field)
                except (requests.RequestException, ValueError, TypeError):
                    pass
        candidates = []
        for field in fields:
            url = addresses[field]
            if not isinstance(url, str) or not url.strip():
                continue
            try:
                url = checked_url(url.strip())
            except ProfileError:
                continue
            if url not in candidates:
                candidates.append(url)
        if not candidates:
            raise ProfileError('해당 참가자의 프로필 사진이 없거나 사진 주소를 조회할 수 없습니다.')
        return candidates

    def photo_url(self, name, reply_url, room=ROOM_ID):
        return self.photo_candidates(name, reply_url, room)[0]

    def photo(self, name, reply_url, room=ROOM_ID):
        for url in self.photo_candidates(name, reply_url, room):
            try:
                return self.download(url)
            except (requests.RequestException, ProfileError):
                continue
        raise ProfileError('원본·큰 사진·기본 사진을 모두 다운로드하지 못했습니다.')

    def download(self, url):
        for _ in range(4):
            url = checked_url(url)
            with self.get(url, timeout=(3, 8), stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = checked_url(urljoin(url, response.headers.get('Location', '')))
                    continue
                response.raise_for_status()
                mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if mime not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'):
                    raise ProfileError('프로필 사진이 지원되는 이미지 형식이 아닙니다.')
                size = response.headers.get('Content-Length')
                if size and (not size.isdecimal() or int(size) > MAX_BYTES):
                    raise ProfileError('프로필 사진 파일이 너무 큽니다.')
                data = bytearray()
                for block in response.iter_content(64 * 1024):
                    data.extend(block)
                    if len(data) > MAX_BYTES:
                        raise ProfileError('프로필 사진 파일이 너무 큽니다.')
                if not image_bytes(data):
                    raise ProfileError('프로필 사진 데이터를 확인할 수 없습니다.')
                return bytes(data)
        raise ProfileError('프로필 사진 주소 이동이 너무 많습니다.')


SERVICE = ProfileService()


def handle(message, room, reply_url, executor, room_name=''):
    match = re.fullmatch(r'!프사(?:\s+(.*))?', message, re.DOTALL)
    if not match:
        return None
    room = str(room)
    if room not in ROOM_IDS:
        return {'ok': True}, 200  # Do not query or reply outside the allowed room.
    name = (match.group(1) or '').strip()

    def text(value):
        SERVICE.post(reply_url, json={'type': 'text', 'room': room, 'data': value}, timeout=10).raise_for_status()

    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        text('사용법: !프사 [정확한 닉네임]')
        return {'ok': True}, 200
    if not SLOTS.acquire(blocking=False):
        text('프로필 사진을 처리 중입니다. 잠시 후 다시 시도해 주세요.')
        return {'ok': True}, 200
    if not SERVICE.reserve(room):
        SLOTS.release()
        text('프로필 사진은 3초 간격으로 조회할 수 있습니다.')
        return {'ok': True}, 200

    def send():
        try:
            data = SERVICE.photo(name, reply_url, room)
            SERVICE.post(reply_url, json={'type': 'image', 'room': room,
                         'data': base64.b64encode(data).decode('ascii')}, timeout=20).raise_for_status()
        except ProfileError as error:
            text(str(error))
        except (requests.RequestException, ValueError, TypeError):
            text('프로필 사진 조회·다운로드·전송에 실패했습니다. Iris 연결을 확인해 주세요.')
        finally:
            SLOTS.release()

    try:
        executor.submit(send)
    except Exception:
        SLOTS.release()
        return {'ok': False, 'error': 'profile_worker_unavailable'}, 503
    return {'ok': True}, 200
