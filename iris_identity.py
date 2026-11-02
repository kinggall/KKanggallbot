"""Resolve only the current quiz participant; never log profile responses."""
import requests


def clean_name(value):
    if not isinstance(value, str):
        return ''
    value = ' '.join(value.split())[:100]
    if value.casefold() in {'', 'null', 'none', 'unknown', '알 수 없음', '참가자'}:
        return ''
    return value


def identity(data, reply_url):
    metadata = data.get('json')
    metadata = metadata if isinstance(metadata, dict) else {}
    sender = data.get('sender')
    sender_info = sender if isinstance(sender, dict) else {}
    player = metadata.get('user_id') or data.get('sender_id') or sender_info.get('id') or sender_info.get('user_id')
    name = clean_name(sender)
    for obj in (sender_info, data, metadata):
        for key in ('nickname', 'sender_name', 'user_name', 'name'):
            name = name or clean_name(obj.get(key))
    if not name and player and str(player).isdigit():
        # Local Iris only: never construct a URL from webhook-provided hosts.
        base = reply_url.rsplit('/', 1)[0]
        try:
            response = requests.get(f'{base}/user/name/{player}', timeout=2)
            response.raise_for_status()
            document = response.json()
            if isinstance(document, dict):
                profile = document.get('payload', document)
                if isinstance(profile, dict):
                    name = clean_name(profile.get('name'))
        except (requests.RequestException, ValueError, TypeError):
            pass
        # OpenChat and normal friends use different tables. Do not infer a
        # participant's name from the room title (in a DM it can be the bot).
        queries = [
            ('open_chat_member', 'SELECT nickname, enc FROM db2.open_chat_member WHERE user_id = ? ORDER BY _id DESC LIMIT 1', 'nickname'),
            ('friends', 'SELECT name, enc FROM db2.friends WHERE id = ? LIMIT 1', 'name'),
            ('recommended_friends', 'SELECT nick_name, enc FROM db2.recommended_friends WHERE user_id = ? LIMIT 1', 'nick_name'),
        ]
        failures = []
        for table, query, field in queries:
            if name:
                break
            try:
                response = requests.post(f'{base}/query', json={
                    'query': query,
                    'bind': [str(player)]}, timeout=2)
                response.raise_for_status()
                document = response.json()
                rows = document.get('data', []) if isinstance(document, dict) else []
                if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
                    name = clean_name(rows[0].get(field))
                if not name:
                    failures.append(table + (':query-error' if isinstance(document,dict) and document.get('error') else ':empty-name'))
            except (requests.RequestException, ValueError, TypeError) as exc:
                failures.append(table + ':' + type(exc).__name__)
        if not name:
            # No profile contents, user IDs, names, or SQL error text in logs.
            print('[Iris 닉네임 조회 실패] ' + ', '.join(failures))
    return str(player or ('name:' + name if name else '')), name
