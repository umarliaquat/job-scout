import json
import unittest
from search_status import status_record

class SearchStatusTests(unittest.TestCase):
    def test_status_is_public_metadata_only(self):
        record=status_record('finished',dict(GITHUB_REPOSITORY='umarliaquat/job-scout',GITHUB_RUN_ID='123',SEARCH_OUTCOME='success',SEARCH_COLLECTED='true',GH_TOKEN='PRIVATE_SECRET'),dict(last_run=dict(finished='2026-11-02T06:41:25+00:00'),notes='PRIVATE_NOTE'))
        self.assertEqual(record['phase'],'completed')
        self.assertEqual(record['run_url'],'https://github.com/umarliaquat/job-scout/actions/runs/123')
        self.assertNotIn('PRIVATE_',json.dumps(record))

    def test_skipped_search_does_not_claim_fresh_collection(self):
        record=status_record('finished',dict(SEARCH_OUTCOME='success',SEARCH_COLLECTED='false',SEARCH_REASON='cooldown',SEARCH_NEXT_ALLOWED='2026-11-02T08:41:25+00:00'),{'last_run':{'finished':'old'}})
        self.assertEqual(record['phase'],'skipped')
        self.assertEqual(record['last_collection'],'old')
        self.assertEqual(record['reason'],'cooldown')
        self.assertEqual(status_record('finished',dict(SEARCH_OUTCOME='failure'),{})['phase'],'failed')

if __name__=='__main__':unittest.main()
