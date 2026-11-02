import json
import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
import search_status
from search_status import status_record

class SearchStatusTests(unittest.TestCase):
    def test_status_branch_has_exact_filename_and_does_not_modify_checkout(self):
        with tempfile.TemporaryDirectory(dir=search_status.ROOT/'tests') as temp:
            root=Path(temp);work=root/'work';origin=root/'origin.git';work.mkdir()
            def run(*args):
                return subprocess.check_output(['git',*args],cwd=work).decode().strip()
            run('init','-q','--bare',str(origin))
            run('init','-q')
            run('remote','add','origin',str(origin))
            run('-c','user.name=Test','-c','user.email=test@example.com','commit','--allow-empty','-qm','Initial')
            original=run('rev-parse','HEAD')
            with patch.object(search_status,'ROOT',work):
                search_status.publish({'schema':1,'phase':'running'})
                search_status.publish({'schema':1,'phase':'completed'})
            run('fetch','-q','origin','scout-status')
            self.assertEqual(run('ls-tree','--name-only','FETCH_HEAD'),'search-status.json')
            self.assertEqual(json.loads(run('show','FETCH_HEAD:search-status.json'))['phase'],'completed')
            self.assertEqual(run('rev-parse','HEAD'),original)
            self.assertEqual(run('status','--porcelain'),'')

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
