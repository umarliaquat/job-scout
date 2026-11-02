import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from account_setup import validate_project

class AccountConnectionTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(enabled=True,url='https://example.supabase.co',publishableKey='sb_publishable_example',provider='github')

    @patch('account_setup.request')
    def test_connection_requires_rls_denied_anonymous_reads_and_enabled_provider(self,request):
        denied=HTTPError('https://example.supabase.co',401,'Permission denied',{},None)
        request.side_effect=[{'version':1,'protected':True},denied,denied,{'external':{'github':True}}]
        self.assertTrue(validate_project(self.config))
        self.assertEqual(request.call_count,4)

    @patch('account_setup.request')
    def test_anonymous_access_blocks_connection_even_with_empty_tables(self,request):
        request.side_effect=[{'version':1,'protected':True},[]]
        with self.assertRaisesRegex(ValueError,'Anonymous reads'):validate_project(self.config)

    @patch('account_setup.request')
    def test_secret_key_is_rejected_before_any_network_call(self,request):
        with self.assertRaises(ValueError):validate_project(dict(self.config,publishableKey='sb_secret_PRIVATE'))
        request.assert_not_called()

    @patch('account_setup.request')
    def test_missing_security_schema_blocks_connection(self,request):
        request.return_value={'version':1,'protected':False}
        with self.assertRaisesRegex(ValueError,'row-level security'):validate_project(self.config)

if __name__=='__main__':unittest.main()
