import unittest
from unittest.mock import Mock, patch
import requests
from iris_identity import identity

URL='http://127.0.0.1:3000/reply'


class IdentityTests(unittest.TestCase):
    def test_iris_default_sender_uses_current_room_nickname_and_same_player(self):
        response=Mock()
        response.json.return_value={'data':[{'user_id':'123','nickname':'OSH','enc':31}]}
        with patch('iris_identity.requests.post',return_value=response) as post, patch('iris_identity.requests.get') as get:
            self.assertEqual(identity({'sender':'Iris','json':{'user_id':'123','chat_id':'456'}},URL),('123','OSH'))
            self.assertEqual(post.call_args.kwargs['json']['bind'],['456','123'])
            self.assertIn('c.link_id = m.link_id',post.call_args.kwargs['json']['query'])
            get.assert_not_called()

    def test_real_metadata_name_preferred_to_iris_placeholder(self):
        with patch('iris_identity.requests.post') as post, patch('iris_identity.requests.get') as get:
            self.assertEqual(identity({'sender':'Iris','json':{'user_id':'123','sender_name':'OSH'}},URL),('123','OSH'))
            get.assert_not_called();post.assert_not_called()

    def test_default_iris_from_user_api_does_not_stop_real_name_lookup(self):
        response=Mock();response.json.return_value={'payload':{'name':'Iris'}}
        member=Mock();member.json.return_value={'data':[{'nickname':'OSH','enc':31}]}
        with patch('iris_identity.requests.get',return_value=response),patch('iris_identity.requests.post',return_value=member):
            self.assertEqual(identity({'sender':'Iris','json':{'user_id':'123'}},URL),('123','OSH'))

    def test_room_lookup_rejects_other_user_and_keeps_stable_id_on_failure(self):
        response=Mock();response.json.return_value={'data':[{'user_id':'999','nickname':'다른사람'}]}
        empty=Mock();empty.json.return_value={'data':[]}
        profile=Mock();profile.json.return_value={'payload':{'name':'Iris'}}
        with patch('iris_identity.requests.post',side_effect=[response,empty,empty]),patch('iris_identity.requests.get',return_value=profile):
            self.assertEqual(identity({'sender':'Iris','json':{'user_id':'123','chat_id':'456'}},URL),('123',''))

    def test_payload_name_variants_and_stable_id(self):
        for fields in [{'sender':'OSH'}, {'sender':{'nickname':'OSH','id':999}},
                       {'sender':None,'nickname':'OSH'}, {'json':{'user_id':'123','sender_name':'OSH'}}]:
            payload={'json':{'user_id':'123'},**fields}
            with patch('iris_identity.requests.get') as get, patch('iris_identity.requests.post') as post:
                self.assertEqual(identity(payload,URL),('123','OSH'))
                get.assert_not_called()
                post.assert_not_called()

    def test_missing_name_uses_local_profile_only(self):
        for document in [{'name':'정달봄'},{'payload':{'name':'정달봄'},'error':None}]:
            response=Mock()
            response.json.return_value=document
            with patch('iris_identity.requests.get',return_value=response) as get, patch('iris_identity.requests.post') as post:
                self.assertEqual(identity({'json':{'user_id':'123'}},URL),('123','정달봄'))
                get.assert_called_once_with('http://127.0.0.1:3000/user/name/123',timeout=2)
                post.assert_not_called()

    def test_older_iris_uses_bound_single_user_query(self):
        response=Mock()
        response.json.return_value={'data':[{'nickname':'왕갤','enc':31}]}
        with patch('iris_identity.requests.get',side_effect=requests.HTTPError), patch('iris_identity.requests.post',return_value=response) as post:
            self.assertEqual(identity({'json':{'user_id':'123'}},URL),('123','왕갤'))
            args=post.call_args.kwargs
            self.assertEqual(args['json']['bind'],['123'])
            self.assertIn('LIMIT 1',args['json']['query'])

    def test_failed_lookup_keeps_id_and_invalid_id_never_enters_url(self):
        with patch('iris_identity.requests.get',side_effect=requests.Timeout), patch('iris_identity.requests.post',side_effect=requests.Timeout):
            self.assertEqual(identity({'json':{'user_id':'123'}},URL),('123',''))
        with patch('iris_identity.requests.get') as get, patch('iris_identity.requests.post') as post:
            self.assertEqual(identity({'json':{'user_id':'../other'}},URL),('../other',''))
            get.assert_not_called()
            post.assert_not_called()

    def test_direct_chat_friend_name_when_openchat_has_no_member(self):
        profile=Mock()
        profile.json.return_value={'payload':{'name':None}}
        empty=Mock()
        empty.json.return_value={'data':[]}
        friend=Mock()
        friend.json.return_value={'data':[{'name':'OSH','enc':'31'}]}
        with patch('iris_identity.requests.get',return_value=profile), patch('iris_identity.requests.post',side_effect=[empty,friend]) as post:
            self.assertEqual(identity({'sender':None,'room':'햄찌','json':{'user_id':'123'}},URL),('123','OSH'))
            self.assertIn('db2.friends',post.call_args.kwargs['json']['query'])
            self.assertEqual(post.call_args.kwargs['json']['bind'],['123'])

    def test_removed_friends_table_falls_back_to_recommended_name(self):
        empty=Mock()
        empty.json.return_value={'data':[]}
        recommended=Mock()
        recommended.json.return_value={'data':[{'nick_name':'OSH','enc':'31'}]}
        with patch('iris_identity.requests.get',side_effect=requests.HTTPError), patch('iris_identity.requests.post',side_effect=[empty,requests.HTTPError(),recommended]):
            self.assertEqual(identity({'json':{'user_id':'123'}},URL),('123','OSH'))
