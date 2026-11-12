"""Read-only local Iris check: report only the requested name and bot profile.

No full participant list, configuration, photo URL or credential is printed.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from iris_profiles import ROOM_IDS, ProfileService, nickname

BASE = 'http://127.0.0.1:3000'
NAMES = {'18182686594126049': '칸코레 진수부에 어서오세요',
         '18250420501835535': '왕갤의 둥지', '18335522977842954': '니나브귀여워'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room', choices=sorted(ROOM_IDS), help='Default: all three permitted rooms')
    parser.add_argument('--name', default='깡갤봇')
    parser.add_argument('--show-self-name', action='store_true', help="Print only the bot's selected room nickname")
    args = parser.parse_args()
    response = requests.get(BASE + '/config', timeout=(2, 5))
    response.raise_for_status()
    document = response.json()
    config = document.get('payload', document) if isinstance(document, dict) else {}
    config = config if isinstance(config, dict) else {}
    uid = str(config.get('bot_id', ''))
    print('Iris bot ID resolved:', uid.isdecimal() and int(uid) > 0)
    print('Requested name equals Iris bot label:', nickname(args.name) == nickname(config.get('bot_name')))
    service = ProfileService()
    missing_self = False
    for room in ([args.room] if args.room else sorted(ROOM_IDS)):
        print(f'\n[{NAMES[room]}]', flush=True)
        try:
            rows = service.room_rows(BASE, room)
            unique = {}
            for row in rows:
                if isinstance(row, dict) and row.get('user_id') is not None:
                    unique.setdefault(str(row['user_id']), row)
            matches = sum(nickname(r.get('nickname')) == nickname(args.name) for r in unique.values())
            own = unique.get(uid)
            print('Member identities:', len(unique))
            print('Exact nickname matches:', matches)
            print('Bot present in this room:', own is not None)
            selected = service.room_bot_profile(BASE, room, uid) if uid.isdecimal() and int(uid) > 0 else None
            print('Selected bot room profile found:', selected is not None)
            if selected is not None:
                print('Selected profile type:', selected.get('profile_type'))
                print('Selected profile nickname matches request:', nickname(selected.get('nickname')) == nickname(args.name))
                print('Selected profile photo present:', any(selected.get(field) for field in
                      ('profile_image_url', 'full_profile_image_url', 'original_profile_image_url')))
                if args.show_self_name:
                    print('Selected bot room nickname:', ' '.join(str(selected.get('nickname') or '(미확인)').split())[:100])
            if own:
                print('Bot room nickname matches requested name:', nickname(own.get('nickname')) == nickname(args.name))
                print('Bot room photo present:', bool(own.get('profile_image_url')))
            elif selected is None:
                missing_self = True
        except (requests.RequestException, ValueError, TypeError) as error:
            print('Room lookup failed:', type(error).__name__)
    if missing_self:
        # Table/column names only, to identify a different self-profile schema
        # without guessing a table or retrieving somebody's personal profile.
        print('\n[OpenChat schema names only]')
        try:
            response = requests.post(BASE + '/query', json={
                'query': "SELECT name AS table_name FROM db2.sqlite_master WHERE type = 'table' AND (name LIKE '%open%' OR name LIKE '%profile%') ORDER BY name",
                'bind': []}, timeout=(2, 5))
            response.raise_for_status()
            data = response.json().get('data', [])
            print(', '.join(str(r['table_name']) for r in data if isinstance(r, dict) and 'table_name' in r))
        except (requests.RequestException, ValueError, TypeError):
            print('Schema lookup unavailable')


if __name__ == '__main__':
    main()
