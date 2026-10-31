import json
import unittest
from unittest.mock import patch
import scout
import publish

class PublishPrivacyTests(unittest.TestCase):
    def test_private_tracking_profile_and_tokens_never_enter_public_snapshot(self):
        j=scout.make_job('Studio','Product Designer','Worldwide','Design SaaS workflows','https://example.com/job','Employer')
        j.update(first_seen=scout.now(),last_seen=scout.now(),state='applied',notes='PRIVATE_NOTE_MARKER',fit_evidence=['PRIVATE_PROFILE_MARKER'],fit_gaps=['PRIVATE_GAP_MARKER'],profile_match='PRIVATE_MATCH_MARKER',published=scout.now(),checked_at=scout.now(),verification='Application form found')
        data=publish.public_snapshot(dict(jobs=[j],sources=[],token='PRIVATE_TOKEN_MARKER',profile_loaded=True,last_run=None))
        raw=json.dumps(data)
        self.assertNotIn('PRIVATE_',raw)
        self.assertFalse(data['profile_loaded'])
        self.assertEqual(data['jobs'][0]['state'],'new')
        self.assertEqual(data['jobs'][0]['notes'],'')

    def test_raw_internal_source_errors_are_not_published(self):
        source=dict(name='Example',status='error',checked=scout.now(),detail='Error at C:/PRIVATE_WORKSPACE/secret')
        data=publish.public_snapshot(dict(jobs=[],sources=[source],last_run=None))
        self.assertNotIn('PRIVATE_WORKSPACE',json.dumps(data))

if __name__=='__main__':unittest.main()
