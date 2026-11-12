"""Exercise real SQLite joins using the columns confirmed on the home device."""
import sqlite3
import unittest
from unittest.mock import Mock

from iris_profiles import ProfileError, ProfileService

BASE = 'http://local'
UID = '42'
ROOMS = ['18182686594126049', '18250420501835535', '18335522977842954']


class SelfProfileTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute("ATTACH DATABASE ':memory:' AS db1")
        self.db.execute("ATTACH DATABASE ':memory:' AS db2")
        self.db.execute('CREATE TABLE db1.chat_rooms (id INTEGER, link_id INTEGER)')
        self.db.execute('CREATE TABLE db2.open_profile (link_id INTEGER, user_id INTEGER, profile_type INTEGER, '
                        'link_member_type INTEGER, nickname TEXT, profile_image_url TEXT, f_profile_image_url TEXT, '
                        'o_profile_image_url TEXT)')
        self.db.execute('CREATE TABLE db2.open_chat_member (_id INTEGER, link_id INTEGER, user_id INTEGER, nickname TEXT, '
                        'profile_image_url TEXT, enc INTEGER)')
        for index, room in enumerate(ROOMS):
            self.db.execute('INSERT INTO db1.chat_rooms VALUES (?, ?)', (room, index + 100))
            prefix = 'open' if index == 0 else 'base'
            # Numeric profile types are passed through, not guessed or used to
            # select a personal photo from another table.
            self.db.execute('INSERT INTO db2.open_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (index + 100, UID, index + 20, 0, prefix + ' nickname',
                             f'https://k.kakaocdn.net/{prefix}-small.png',
                             f'https://k.kakaocdn.net/{prefix}-full.png',
                             f'https://k.kakaocdn.net/{prefix}-original.png'))

        def get(url, **_kwargs):
            result = Mock(status_code=200)
            result.json.return_value = ({'bot_id': UID, 'bot_name': '깡갤봇'} if url.endswith('/config')
                                        else {'payload': {'members': []}})
            return result

        def post(_url, *, json, **_kwargs):
            result = Mock(status_code=200)
            rows = [dict(r) for r in self.db.execute(json['query'], json['bind']).fetchall()]
            result.json.return_value = {'data': rows}
            return result

        self.service = ProfileService(get=Mock(side_effect=get), post=Mock(side_effect=post))

    def tearDown(self):
        self.db.close()

    def test_self_missing_from_participants_uses_selected_room_profile_in_all_three_rooms(self):
        for index, room in enumerate(ROOMS):
            with self.subTest(room=room):
                prefix = 'open' if index == 0 else 'base'
                urls = self.service.photo_candidates('깡갤봇', BASE + '/reply', room)
                self.assertEqual(urls, [f'https://k.kakaocdn.net/{prefix}-original.png',
                                        f'https://k.kakaocdn.net/{prefix}-full.png',
                                        f'https://k.kakaocdn.net/{prefix}-small.png'])
        for call in self.service.post.call_args_list:
            query = call.kwargs['json']['query']
            self.assertNotIn('friends', query)
            if 'open_profile' in query:
                self.assertIn('c.link_id = p.link_id', query)
                self.assertIn('p.user_id = ?', query)
                self.assertNotIn('enc', query)
                self.assertNotIn('p._id', query)

    def test_other_user_or_other_room_never_substitutes_for_self(self):
        self.assertIsNone(self.service.room_bot_profile(BASE, ROOMS[0], '99'))
        self.assertIsNone(self.service.room_bot_profile(BASE, '777', UID))

    def test_actual_bot_room_nickname_is_also_accepted(self):
        self.assertEqual(self.service.photo_candidates('open nickname', BASE + '/reply', ROOMS[0])[0],
                         'https://k.kakaocdn.net/open-original.png')

    def test_duplicate_self_profile_is_not_arbitrarily_selected(self):
        self.db.execute('INSERT INTO db2.open_profile SELECT * FROM db2.open_profile WHERE link_id = 100')
        with self.assertRaisesRegex(ProfileError, '여러 개'):
            self.service.photo_candidates('깡갤봇', BASE + '/reply', ROOMS[0])

    def test_thumbnail_is_used_when_selected_profile_has_no_large_photo(self):
        self.db.execute('UPDATE db2.open_profile SET f_profile_image_url = NULL, o_profile_image_url = NULL WHERE link_id = 100')
        self.assertEqual(self.service.photo_candidates('깡갤봇', BASE + '/reply', ROOMS[0]),
                         ['https://k.kakaocdn.net/open-small.png'])

    def test_empty_selected_profile_does_not_use_other_rooms_base_photo(self):
        self.db.execute('UPDATE db2.open_profile SET profile_image_url = NULL, f_profile_image_url = NULL, '
                        'o_profile_image_url = NULL WHERE link_id = 100')
        with self.assertRaisesRegex(ProfileError, '사진이 없거나'):
            self.service.photo_candidates('깡갤봇', BASE + '/reply', ROOMS[0])
