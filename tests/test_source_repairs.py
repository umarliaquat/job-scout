import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import scout
import publish

class SourceRepairTests(unittest.TestCase):
    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_role_cards_keep_application_routes_and_requirements_separate(self,fetch,_):
        text = ('<h1>Careers</h1><article><h2>Full-stack Engineer</h2>Remote Pakistan Rust required '
                '<a href="mailto:engineering@example.com?subject=Application">Apply</a></article>'
                '<article><h2>Product Designer</h2>Contract Remote Pakistan Figma '
                '<a href="mailto:design@example.com?subject=Application">Apply via email</a></article>'
                '<footer>US only <a href="mailto:footer@example.com">Careers</a></footer>')
        fetch.return_value=(text,'https://example.com/careers',False)
        board=dict(company='Example',website='https://example.com',url='https://example.com/careers',
                   slug='page',location='Remote Pakistan',role_sections=True)
        jobs,_=scout.career_page_jobs(board,24)
        design=next(j for j in jobs if j['title']=='Product Designer')
        self.assertNotIn('Rust',design['description'])
        self.assertNotIn('US only',design['description'])
        self.assertIsNone(design['published'])
        verified=scout.verify(design)
        self.assertEqual(verified['verification'],'Email applications listed')
        self.assertEqual(verified['application_email'],'design@example.com')
        self.assertEqual(scout.opportunity(scout.score(verified,30))['priority'],'review')

    def test_role_cards_require_scoped_remote_and_application_evidence(self):
        board=dict(company='Example',website='https://example.com',slug='page',location='Remote Pakistan')
        text=('<h2>Product Designer</h2>On-site Pakistan <a href="mailto:hr@example.com">Apply</a>'
              '<h2>UX Designer</h2>Remote Figma'
              '<h2>Web Designer</h2>Hybrid remote <a href="mailto:hr@example.com">Apply</a>'
              '<footer>Remote worldwide <a href="mailto:hr@example.com">Apply</a></footer>')
        self.assertEqual(scout.career_section_jobs(board,text,'https://example.com/careers',False),[])

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_removed_or_ambiguous_card_does_not_verify_from_another_role(self,fetch,_):
        for text in ('<h2>Frontend Engineer</h2>Remote <a href="mailto:hr@example.com">Apply</a>',
                     '<h2>Product Designer</h2>Remote <h2>Product Designer</h2>Remote'):
            fetch.return_value=(text,'https://example.com/careers',False)
            job=scout.make_job('Example','Product Designer','Remote Pakistan','Figma',
                               'https://example.com/careers','Test',section_title='Product Designer')
            self.assertEqual(scout.verify(job)['verification'],'Needs review')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    @patch('scout.board_jobs')
    def test_embedded_employer_board_uses_its_public_adapter(self,adapter,fetch,_):
        fetch.return_value=('<iframe src="https://jobs.ashbyhq.com/example/embed"></iframe>','https://example.com/careers',False)
        adapter.return_value=([{'id':'role'}],False)
        records,_=scout.career_page_jobs(dict(company='Example',website='https://example.com',url='https://example.com/careers',slug='page'),0)
        self.assertEqual(records,[{'id':'role'}])
        self.assertEqual(adapter.call_args.args[0]['slug'],'example')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_button_based_remote_role_is_discovered_without_claiming_application_verified(self,fetch,_):
        fetch.return_value=('<h1>UI/UX Designer</h1>Remote <button>Apply Now</button> Design products.','https://example.com/careers/designer',False)
        records,_=scout.career_page_jobs(dict(company='Example',website='https://example.com',url='https://example.com/careers/designer',slug='page'),0)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['verification'],'Not checked')
        self.assertIsNone(records[0]['published'])

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_unreadable_job_inventory_is_manual_not_successful_zero(self,fetch,_):
        fetch.return_value=('<h1>Careers</h1><div id="js-jobs"></div>','https://example.com/careers',False)
        with self.assertRaises(scout.SourceNeedsReview):
            scout.career_page_jobs(dict(company='Example',website='https://example.com',url='https://example.com/careers',slug='page'),0)

    @patch('scout.time.sleep')
    @patch('scout.config',return_value=dict(arbeitnow_max_pages=3,max_age_days=30))
    @patch('scout.json_fetch')
    def test_later_page_throttle_preserves_partial_results_without_retry(self,fetch,_,sleep):
        item=dict(company_name='Studio',title='Product Designer',remote=True,location='Worldwide',description='Remote design',url='https://example.com/job',created_at=scout.now())
        fetch.side_effect=[({'data':[item],'links':{'next':'page2'}},False),HTTPError('https://example.com',429,'Throttled',{},None)]
        with self.assertRaises(scout.SourceNeedsReview) as caught:
            scout.arbeitnow_jobs('arbeitnow',0)
        self.assertEqual(len(caught.exception.jobs),1)
        self.assertEqual(fetch.call_count,2)

    def test_collection_report_explains_new_design_exclusions(self):
        previous={'jobs':[{'id':'old'}],'last_run':{'finished':'yesterday'}}
        common=dict(category='Product design',priority='review',freshness='Recent',verification='Needs review')
        records=[dict(common,id='old'),dict(common,id='new'),dict(common,id='undated',freshness='Unknown date')]
        report=publish.collection_report(records,previous)
        self.assertEqual(report['added_design'],2)
        self.assertEqual(report['qualified_design'],0)
        self.assertEqual(report['excluded']['application_unverified'],1)
        self.assertEqual(report['excluded']['undated'],1)
        self.assertFalse(publish.collection_report(records,None)['comparison_available'])

    def test_public_source_failures_retain_safe_actionable_reasons(self):
        self.assertIn('Rate limit',publish.source_detail(dict(status='error',detail='HTTP Error 429 at C:/PRIVATE_PATH')))
        self.assertNotIn('PRIVATE_PATH',publish.source_detail(dict(status='error',detail='HTTP Error 429 at C:/PRIVATE_PATH')))
        self.assertIn('manual',publish.source_detail(dict(status='manual',detail='unreadable')))

    def test_working_student_role_requires_eligibility_review(self):
        record=dict(title='Werkstudent UX/UI Design',category='Product design',freshness='Recent',verification='Application form found',eligibility='Worth a chance',description='',location='Berlin')
        result=scout.opportunity(record)
        self.assertEqual(result['priority'],'review')
        self.assertIn('enrollment',result['main_catch'])

if __name__=='__main__':unittest.main()
