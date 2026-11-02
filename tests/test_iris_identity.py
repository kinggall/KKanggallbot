import unittest
from unittest.mock import Mock, patch
import requests
from iris_identity import identity

URL='http://127.0.0.1:3000/reply'


class IdentityTests(unittest.TestCase):
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
