import base64
import unittest
from unittest.mock import Mock, patch
import requests
import iris_profiles as profiles


PHOTO = b'\x89PNG\r\n\x1a\n' + b'fake-test-image'
URL = 'https://k.kakaocdn.net/test/profile.png'


def response(rows=None, status=200, data=PHOTO, mime='image/png'):
    r=Mock(status_code=status, headers={'Content-Type':mime})
    r.json.return_value={'payload':{'members':rows if rows is not None else []}}
    r.iter_content.return_value=iter([data])
    r.__enter__=Mock(return_value=r)
    r.__exit__=Mock(return_value=False)
    return r


class Inline:
    def submit(self, fn):
        fn()


class ProfileTests(unittest.TestCase):
    def service(self,rows):
        return profiles.ProfileService(get=Mock(return_value=response(rows)),post=Mock(),clock=lambda:100)

    def test_exact_nickname_and_openchat_photo(self):
        s=self.service([{'user_id':'1','nickname':'테스트 닉','profile_image_url':URL}])
        self.assertEqual(s.photo_url('테스트  닉','http://127.0.0.1:3000/reply'),URL)
        self.assertIn('/room/'+profiles.ROOM_ID+'/members',s.get.call_args.args[0])
        self.assertTrue(all(c.kwargs['json']['bind']==[profiles.ROOM_ID,'1'] for c in s.post.call_args_list))

    def test_duplicate_nickname_is_not_arbitrarily_chosen(self):
        s=self.service([{'user_id':str(i),'nickname':'동명','profile_image_url':URL} for i in (1,2)])
        with self.assertRaises(profiles.ProfileError):s.photo_url('동명','http://local/reply')

    def test_latest_record_per_user(self):
        s=self.service([{'user_id':'1','nickname':'새닉','profile_image_url':URL},
                        {'user_id':'1','nickname':'옛닉','profile_image_url':URL}])
        with self.assertRaises(profiles.ProfileError):s.photo_url('옛닉','http://local/reply')

    def test_missing_name_photo_and_bad_payload(self):
        for rows in ([],[{'nickname':'닉','profile_image_url':''}]):
            with self.assertRaises(profiles.ProfileError):self.service(rows).photo_url('닉','http://local/reply')
        s=self.service([]);s.get.return_value.json.return_value={'payload':None}
        with self.assertRaises(profiles.ProfileError):s.photo_url('닉','http://local/reply')
        s=self.service([]);s.get.return_value.json.return_value={'error':'private server error','payload':{'members':[]}}
        with self.assertRaises(profiles.ProfileError) as error:s.photo_url('닉','http://local/reply')
        self.assertNotIn('private server error',str(error.exception))

    def test_old_iris_query_is_scoped_to_room(self):
        s=self.service([]);s.get.return_value.status_code=404
        s.post.return_value.json.return_value={'data':[{'user_id':'1','nickname':'닉','profile_image_url':URL}]}
        self.assertEqual(s.photo_url('닉','http://local/reply'),URL)
        body=s.post.call_args_list[0].kwargs['json']
        self.assertEqual(body['bind'],[profiles.ROOM_ID])
        self.assertIn('c.id = ?',body['query'])
        self.assertIn('c.link_id = m.link_id',body['query'])
        self.assertNotIn('friends',body['query'])

    def test_only_https_kakao_image_hosts(self):
        for url in ('http://k.kakaocdn.net/a','https://127.0.0.1/a','https://kakaocdn.net.attacker.test/a',
                    'https://evil.test/a','file:///tmp/a','https://u:p@k.kakaocdn.net/a',
                    'https://k.kakaocdn.net:3000/a'):
            with self.subTest(url=url),self.assertRaises(profiles.ProfileError):profiles.checked_url(url)

    def test_image_download_and_size_limits(self):
        s=self.service([]);s.get.return_value=response()
        self.assertEqual(s.download(URL),PHOTO)
        self.assertFalse(s.get.call_args.kwargs['allow_redirects'])
        for r in (response(mime='text/html'),response(data=b'not an image')):
            s.get.return_value=r
            with self.assertRaises(profiles.ProfileError):s.download(URL)
        with patch.object(profiles,'MAX_BYTES',10):
            s.get.return_value=response()
            with self.assertRaises(profiles.ProfileError):s.download(URL)

    def test_redirect_to_local_address_blocked(self):
        r=response(status=302);r.headers['Location']='http://127.0.0.1:3000/query'
        s=self.service([]);s.get.return_value=r
        with self.assertRaises(profiles.ProfileError):s.download(URL)
        self.assertEqual(s.get.call_count,1)

    def test_handler_room_gate_and_usage(self):
        s=self.service([])
        with patch.object(profiles,'SERVICE',s):
            self.assertIsNone(profiles.handle('!퀴즈',profiles.ROOM_ID,'http://local/reply',Inline()))
            profiles.handle('!프사 닉','other','http://local/reply',Inline())
            s.get.assert_not_called();s.post.assert_not_called()
            profiles.handle('!프사',profiles.ROOM_ID,'http://local/reply',Inline())
            self.assertIn('사용법',s.post.call_args.kwargs['json']['data'])

    def test_sends_base64_photo_and_throttles(self):
        s=self.service([]);s.photo=Mock(return_value=PHOTO)
        with patch.object(profiles,'SERVICE',s):
            profiles.handle('!프사 닉',profiles.ROOM_ID,'http://local/reply',Inline())
            body=s.post.call_args.kwargs['json']
            self.assertEqual(body['type'],'image')
            self.assertEqual(base64.b64decode(body['data']),PHOTO)
            self.assertEqual(body['room'],profiles.ROOM_ID)
            profiles.handle('!프사 닉',profiles.ROOM_ID,'http://local/reply',Inline())
            self.assertIn('3초',s.post.call_args.kwargs['json']['data'])
            self.assertEqual(s.photo.call_count,1)

    def test_download_failure_is_sanitized(self):
        s=self.service([]);s.photo=Mock(side_effect=requests.RequestException('private-url-secret'))
        with patch.object(profiles,'SERVICE',s):
            profiles.handle('!프사 닉',profiles.ROOM_ID,'http://local/reply',Inline())
        self.assertNotIn('private-url-secret',s.post.call_args.kwargs['json']['data'])

    def test_reserve_allows_exactly_three_seconds(self):
        tick=[100.0]
        s=profiles.ProfileService(clock=lambda:tick[0])
        self.assertTrue(s.reserve())
        tick[0]=102.99
        self.assertFalse(s.reserve())
        tick[0]=103.0
        self.assertTrue(s.reserve())

    def test_named_rooms_use_their_own_destination_and_cooldown(self):
        s=self.service([]);s.photo=Mock(return_value=PHOTO)
        with patch.object(profiles,'SERVICE',s):
            for room,title in [('111','왕갤의 둥지'),('222','니나브귀여워')]:
                profiles.handle('!프사 닉',room,'http://local/reply',Inline(),room_name=title)
                s.photo.assert_called_with('닉','http://local/reply',room)
                self.assertEqual(s.post.call_args.kwargs['json']['room'],room)
                self.assertEqual(s.post.call_args.kwargs['json']['type'],'image')
            self.assertEqual(s.photo.call_count,2)
            profiles.handle('!프사 닉','111','http://local/reply',Inline(),room_name='왕갤의 둥지')
            self.assertIn('3초',s.post.call_args.kwargs['json']['data'])
            profiles.handle('!프사 닉','333','http://local/reply',Inline(),room_name='다른 방')
            self.assertEqual(s.photo.call_count,2)

    def test_member_and_high_resolution_queries_use_requested_room(self):
        s=self.service([{'user_id':'1','nickname':'닉','profile_image_url':URL}])
        s.photo_candidates('닉','http://local/reply','222')
        self.assertIn('/room/222/members',s.get.call_args.args[0])
        for call in s.post.call_args_list:
            self.assertEqual(call.kwargs['json']['bind'],['222','1'])

    def test_original_then_full_then_thumbnail(self):
        original='https://k.kakaocdn.net/original.png'
        full='https://k.kakaocdn.net/full.png'
        s=self.service([{'user_id':'1','nickname':'닉','profile_image_url':URL,
                        'original_profile_image_url':original,'full_profile_image_url':full}])
        self.assertEqual(s.photo_candidates('닉','http://local/reply'),[original,full,URL])
        s.post.assert_not_called()
        s.download=Mock(return_value=PHOTO)
        self.assertEqual(s.photo('닉','http://local/reply'),PHOTO)
        s.download.assert_called_once_with(original)

    def test_high_resolution_query_checks_room_user_and_nickname(self):
        s=self.service([{'user_id':'42','nickname':'닉','profile_image_url':URL}])
        original='https://k.kakaocdn.net/original.png'
        good=response();good.json.return_value={'data':[{'user_id':'42','nickname':'닉','original_profile_image_url':original}]}
        missing=response();missing.json.return_value={'error':'no such column'}
        s.post.side_effect=[good,missing]
        self.assertEqual(s.photo_candidates('닉','http://local/reply'),[original,URL])
        for call in s.post.call_args_list:
            self.assertEqual(call.kwargs['json']['bind'],[profiles.ROOM_ID,'42'])
            self.assertIn('m.user_id = ?',call.kwargs['json']['query'])
        s.post.side_effect=None
        good.json.return_value={'data':[{'user_id':'99','nickname':'닉','original_profile_image_url':original}]}
        s.post.return_value=good
        self.assertEqual(s.photo_candidates('닉','http://local/reply'),[URL])

    def test_large_download_failure_falls_back_without_resize(self):
        s=self.service([])
        original='https://k.kakaocdn.net/original.png'
        full='https://k.kakaocdn.net/full.png'
        s.photo_candidates=Mock(return_value=[original,full,URL])
        s.download=Mock(side_effect=[requests.HTTPError(),PHOTO])
        self.assertEqual(s.photo('닉','http://local/reply'),PHOTO)
        self.assertEqual([c.args[0] for c in s.download.call_args_list],[original,full])

    def test_optional_columns_unavailable_keeps_working_thumbnail(self):
        s=self.service([{'user_id':'1','nickname':'닉','profile_image_url':URL}])
        s.post.side_effect=requests.Timeout()
        self.assertEqual(s.photo_candidates('닉','http://local/reply'),[URL])

    def test_webhook_routes_profiles_with_numeric_room(self):
        import bot
        with patch.object(bot.iris_profiles,'handle',return_value=({'ok':True},200)) as handle:
            result=bot.app.test_client().post('/webhook',json={'msg':'!프사 닉','room':'방 이름','json':{'chat_id':profiles.ROOM_ID}})
            self.assertEqual(result.status_code,200)
            self.assertEqual(handle.call_args.args[:2],('!프사 닉',profiles.ROOM_ID))
