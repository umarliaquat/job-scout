import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import scout


def job(**values):
    j = scout.make_job('Example Studio','Product Designer','Remote worldwide','A small team designs software.','https://example.com/jobs/designer','Test')
    j.update(values)
    return j


class EvidenceTests(unittest.TestCase):
    def test_generic_marketing_does_not_establish_eligibility(self):
        self.assertEqual(scout.geography('', 'Our product is used worldwide.')[0], 'Worth a chance')
        self.assertEqual(scout.geography('Germany', 'Work from anywhere.')[0], 'Worth a chance')
        self.assertEqual(scout.geography('Worldwide', 'Must be based in Germany.')[0], 'Restricted / review')
        self.assertEqual(scout.geography('Worldwide', 'Must be passionate about design.')[0], 'Worldwide advertised')

    def test_explicit_restrictions_beat_worldwide(self):
        result = scout.geography('Worldwide', 'Applicants must reside in the United States.')
        self.assertEqual(result[0],'Restricted / review')
        self.assertIn('United States',result[1])

    def test_timezone_does_not_imply_country(self):
        self.assertEqual(scout.geography('CET timezone', 'Remote role.')[0], 'Worth a chance')

    def test_temporary_work_abroad_perk_is_not_worldwide_hiring(self):
        self.assertEqual(scout.geography('Remote job','Work from anywhere for 4 weeks/year.')[0],'Worth a chance')
        self.assertIn('DACH',scout.geography('remote','Location Remote, with the primary location in the DACH region.')[1])

    def test_roles_exclude_mechanical_and_incidental_mentions(self):
        self.assertIsNone(scout.role('Mechanical Design Engineer'))
        self.assertIsNone(scout.role('Product Manager (ex-product engineer)'))
        self.assertEqual(scout.role('Senior UI/UX Designer'),'Product design')
        self.assertIsNone(scout.make_job('Example','Product Designer','London','Our team is fully remote','https://example.com/job','Test',workplace='hybrid'))

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_employer_cross_link_is_corroboration_not_legitimacy(self, fetch, _):
        fetch.return_value=('<h1>Example</h1><a href="https://jobs.ashbyhq.com/example">Careers</a>','https://example.com',False)
        result=scout.employer_evidence('https://example.com','ashby:example')
        self.assertEqual(result['identity_status'],'Employer site links board')
        self.assertIn('not the legitimacy',result['identity_evidence'])

    def test_unknown_and_updated_dates_never_become_recent(self):
        j = scout.score(job(published=None,modified=scout.now()),30)
        self.assertEqual(j['freshness'],'Unknown date')
        old = (datetime.now(timezone.utc)-timedelta(days=60)).isoformat()
        self.assertEqual(scout.score(job(published=old),30)['freshness'],'Older')

    def test_offset_dates_preserve_actual_time(self):
        self.assertEqual(scout.date('2026-10-20T10:00:00-05:00'),'2026-10-20T15:00:00+00:00')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_newsletter_form_is_not_an_application(self, fetch, _):
        fetch.return_value=('<h1>Product Designer</h1><p>Send your resume when applying.</p><form><input type="email" name="email"></form>','https://example.com/jobs/designer',False)
        self.assertEqual(scout.verify(job())['verification'],'Needs review')

    def test_unrelated_forms_cannot_combine_into_application_evidence(self):
        page=scout.Page()
        page.feed('<form><input name="email"></form><form><input name="resume"></form>')
        self.assertFalse(scout.application_form(page))
        contact=scout.Page()
        contact.feed('<form action="/contact"><input name="email"><input name="first_name"></form>')
        self.assertFalse(scout.application_form(contact))

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_apply_link_is_followed_and_closed_destination_rejected(self, fetch, _):
        fetch.side_effect=[('<h1>Product Designer</h1><a href="/apply">Apply now</a>','https://example.com/jobs/designer',False),('<h1>This job is closed</h1>','https://example.com/apply',False)]
        self.assertEqual(scout.verify(job())['verification'],'Closed')
        self.assertEqual(fetch.call_count,2)

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_expiry_on_application_destination_is_checked(self, fetch, _):
        block=json.dumps({'@type':'JobPosting','title':'Product Designer','validThrough':'2020-01-01'})
        fetch.side_effect=[('<h1>Product Designer</h1><a href="/apply">Apply now</a>','https://example.com/jobs/designer',False),(f'<h1>Product Designer</h1><script type="application/ld+json">{block}</script>','https://example.com/apply',False)]
        self.assertEqual(scout.verify(job())['verification'],'Closed')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_role_specific_form_is_detected_without_submission(self, fetch, _):
        fetch.return_value=('<h1>Product Designer</h1><form><input type="email" name="email"><input name="first_name"><input type="file" name="resume"></form>','https://example.com/jobs/designer',False)
        self.assertEqual(scout.verify(job())['verification'],'Application form found')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_expired_structured_posting_is_closed(self, fetch, _):
        block=json.dumps({'@type':'JobPosting','title':'Product Designer','validThrough':'2020-01-01'})
        fetch.return_value=(f'<h1>Product Designer</h1><script type="application/ld+json">{block}</script>','https://example.com/jobs/designer',False)
        self.assertEqual(scout.verify(job())['verification'],'Closed')

    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_footer_mentions_of_closed_jobs_do_not_close_vacancy(self, fetch, _):
        fetch.return_value=('<h1>Product Designer</h1><p>We retain applications for closed positions.</p><form><input name="email"><input name="resume"></form>','https://example.com/jobs/designer',False)
        self.assertEqual(scout.verify(job())['verification'],'Application form found')

    def test_structured_graph_and_list_parsing(self):
        blocks=list(scout.posting_blocks([{'@graph':[{'@type':['Thing','JobPosting'],'title':'Product Designer'}]}]))
        self.assertEqual(len(blocks),1)

    def test_private_destinations_rejected(self):
        for url in ('file:///etc/passwd','http://127.0.0.1','http://localhost:8765','http://169.254.169.254'):
            with self.assertRaises(ValueError):
                scout.public_url(url)


class NewEvidenceTests(unittest.TestCase):
    @patch('scout.permitted',return_value=True)
    @patch('scout.fetch')
    def test_explicit_email_application_route_and_support_footer(self, fetch, _):
        fetch.return_value=('<h1>Product Designer</h1><a href="mailto:jobs@example.com">Apply by email</a>','https://example.com/jobs/designer',False)
        result=scout.verify(job())
        self.assertEqual(result['verification'],'Email applications listed')
        self.assertEqual(result['application_email'],'jobs@example.com')
        fetch.return_value=('<h1>Product Designer</h1><a href="mailto:support@example.com">Support</a>','https://example.com/jobs/designer',False)
        self.assertEqual(scout.verify(job())['verification'],'Needs review')

    def test_unknown_date_and_unverified_page_stay_in_review(self):
        base=job(freshness='Unknown',verification='Application form found',category='Product design',eligibility='Pakistan listed')
        self.assertEqual(scout.opportunity(base)['priority'],'review')
        base.update(freshness='Recent',verification='Employer page listed')
        self.assertEqual(scout.opportunity(base)['priority'],'review')

    def test_profile_does_not_infer_production_coding_skill(self):
        base=job(title='Design Engineer',description='Build React TypeScript SaaS interfaces in Figma',category='Design engineering',freshness='Recent',verification='Application form found',eligibility='Worldwide advertised')
        profile={'years_experience':5,'evidence_groups':[{'label':'Figma','terms':['Figma']}]}
        result=scout.profile_match(scout.opportunity(base),profile)
        self.assertTrue(result['fit_gaps'])
        self.assertIn('does not establish production',result['fit_gaps'][0])


class ExpandedDiscoveryTests(unittest.TestCase):
    @patch('scout.himalayas_json')
    @patch('scout.config')
    def test_himalayas_update_is_not_publication_and_apply_link_preserved(self,cfg,fetch):
        cfg.return_value=dict(himalayas_queries=['product designer'],himalayas_pages_per_query=1)
        item=dict(title='Product Designer',companyName='Studio',guid='https://himalayas.app/companies/studio/jobs/designer',applicationLink='https://example.com/apply?source=himalayas',locationRestrictions=['Pakistan'],pubDate=1793344839,description='Design SaaS products',companySlug='studio')
        fetch.return_value=({'jobs':[item]},False)
        jobs,_=scout.himalayas_jobs(12)
        self.assertEqual(len(jobs),1)
        self.assertIsNone(jobs[0]['published'])
        self.assertIsNotNone(jobs[0]['modified'])
        self.assertEqual(jobs[0]['application_url'],item['applicationLink'])

    @patch('scout.himalayas_json')
    def test_himalayas_closed_status_wins_without_application_fetch(self,fetch):
        from urllib.error import HTTPError
        error=HTTPError('https://himalayas.app',410,'Gone',{},None)
        fetch.side_effect=error
        j=job(himalayas_guid='https://himalayas.app/companies/studio/jobs/designer')
        self.assertEqual(scout.verify(j)['verification'],'Closed')
        error.close()

    @patch('scout._verify_application')
    @patch('scout.himalayas_json')
    def test_himalayas_status_does_not_replace_attributed_apply_link(self,fetch,verify):
        guid='https://himalayas.app/companies/studio/jobs/designer'
        j=job(himalayas_guid=guid,application_url=guid+'?utm_source=api')
        fetch.return_value=({'job':{'guid':guid}},False)
        verify.return_value=dict(j,verification='Application form found',verification_evidence='Form fields found.',application_url='https://example.com/apply')
        result=scout.verify(j)
        self.assertEqual(result['application_url'],guid+'?utm_source=api')
        self.assertEqual(result['verified_destination'],'https://example.com/apply')

    def test_worldwide_feed_does_not_override_pakistan_timezone_exclusion(self):
        j=job(himalayas_timezones=[0,1],location='Worldwide')
        self.assertEqual(scout.score(j,30)['eligibility'],'Worth a chance')

    @patch('scout.json_fetch')
    @patch('scout.config')
    def test_arbeitnow_uk_pages_and_skips_onsite(self,cfg,fetch):
        cfg.return_value=dict(arbeitnow_max_pages=20,max_age_days=30)
        item=dict(company_name='Studio',title='Product Designer',location='Remote worldwide',description='Design software',url='https://example.com/job',created_at=scout.now(),remote=True)
        fetch.side_effect=[({'data':[dict(item,remote=False)],'links':{'next':'page2'}},False),({'data':[item],'links':{'next':None}},False)]
        jobs,_=scout.arbeitnow_jobs('arbeitnow_uk',12)
        self.assertEqual(len(jobs),1)
        self.assertEqual(fetch.call_count,2)
        self.assertIn('www.arbeitnow.co.uk',fetch.call_args_list[0].args[0])

    def test_himalayas_daily_cap_stops_before_network(self):
        with tempfile.TemporaryDirectory(dir=scout.ROOT) as tmp,patch.object(scout,'DATA',Path(tmp)),patch('scout.config',return_value={'himalayas_daily_request_cap':1}),patch('scout.json_fetch') as fetch:
            Path(tmp,'himalayas-usage.json').write_text(json.dumps({'date':datetime.now(timezone.utc).date().isoformat(),'requests':1}))
            with self.assertRaisesRegex(ValueError,'safety cap'):
                scout.himalayas_json('https://himalayas.app/jobs/api/search?q=designer')
            fetch.assert_not_called()

    def test_follow_employer_recognizes_workable_and_eu_greenhouse(self):
        self.assertEqual(scout.board_from_url('https://apply.workable.com/pavago/j/ABC/','Pavago')['kind'],'workable')
        self.assertIsNone(scout.board_from_url('https://apply.workable.com/j/ABC','Unknown'))
        self.assertEqual(scout.board_from_url('https://job-boards.eu.greenhouse.io/defuselabs/jobs/123','Defuse')['slug'],'defuselabs')

    @patch('scout.json_fetch')
    def test_workable_groups_countries_and_uses_employer_date(self, fetch):
        item=dict(title='Product Designer',shortcode='ABC',telecommuting=True,published_on='2026-10-19',locations=[])
        detail=dict(title='Product Designer',state='published',published='2026-10-19T00:00:00Z',description='Design SaaS workflows',requirements='',benefits='')
        fetch.side_effect=[({'jobs':[dict(item,country='Pakistan'),dict(item,country='Pakistan')]},False),(detail,False)]
        with patch('scout.age_days',return_value=12):
            jobs,cached=scout.workable_jobs(dict(company='Studio',slug='studio',website='https://example.com'),12)
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['location'],'Pakistan')
        self.assertEqual(jobs[0]['published'],'2026-10-19T00:00:00+00:00')
        self.assertEqual(jobs[0]['verification'],'Not checked')

    @patch('scout.json_fetch')
    def test_workable_does_not_import_unpublished_or_internal_jobs(self, fetch):
        item=dict(title='Product Designer',shortcode='ABC',telecommuting=True,published_on='2026-10-19',country='Pakistan',locations=[])
        for state,internal in [('closed',False),('published',True)]:
            fetch.side_effect=[({'jobs':[item]},False),({'state':state,'isInternal':internal},False)]
            with patch('scout.age_days',return_value=12):
                self.assertEqual(scout.workable_jobs(dict(company='Studio',slug='studio'),12)[0],[])

    def test_physical_design_is_excluded_and_visual_design_is_distinct(self):
        self.assertIsNone(scout.role('Overhead Line (OHL) Design engineer'))
        self.assertEqual(scout.role('Senior Multi-Skilled Designer, AI-Fluent'),'Web / visual design')

    def test_large_experience_gap_is_not_promising(self):
        j=job(description='7+ years of experience designing products in Figma.',category='Product design',freshness='Recent',verification='Application form found',eligibility='Worldwide advertised')
        self.assertEqual(scout.profile_match(scout.opportunity(j),{'years_experience':5})['priority'],'stretch')

    def test_required_russian_is_visible_as_a_prerequisite(self):
        j=job(description='English at B2-C1 and Russian.',category='Product design',freshness='Recent',verification='Application form found',eligibility='Worldwide advertised')
        result=scout.profile_match(scout.opportunity(j),{'years_experience':5})
        self.assertEqual(result['priority'],'stretch')
        self.assertIn('Russian',result['main_catch'])


class StorageTests(unittest.TestCase):
    def test_attention_priority_does_not_confuse_open_with_suitable(self):
        base=job(freshness='Recent',verification='Application form found',category='Product design',eligibility='Restricted / review')
        self.assertEqual(scout.opportunity(base)['priority'],'stretch')
        base.update(eligibility='Worldwide advertised')
        self.assertEqual(scout.opportunity(base)['priority'],'promising')
        base.update(verification='Needs review')
        self.assertEqual(scout.opportunity(base)['priority'],'review')
        base.update(freshness='Older')
        self.assertEqual(scout.opportunity(base)['priority'],'archive')

    def test_onsite_description_cannot_be_a_remote_recommendation(self):
        j=job(freshness='Recent',verification='Employer board listed',description='Location On-site in New York, United States.')
        self.assertEqual(scout.opportunity(j)['priority'],'archive')

    def test_encoded_markup_is_removed_from_summaries(self):
        self.assertEqual(scout.plain('&lt;p&gt;Design &amp;amp; build&lt;/p&gt;'),'Design & build')

    def test_scan_preserves_notes_and_does_not_close_on_source_failure(self):
        with tempfile.TemporaryDirectory(dir=scout.ROOT) as tmp, patch.object(scout,'DATA',Path(tmp)):
            cfg={'feeds':[],'boards':[{'kind':'ashby','slug':'example','company':'Example'}], 'cache_hours':12,'max_age_days':30,'verify_limit':10,'blocked_companies':[]}
            j=job(published=scout.now(),direct=True,board_key='ashby:example')
            with patch('scout.config',return_value=cfg),patch('scout.board_jobs',return_value=([j],False)),patch('scout.verify',side_effect=lambda j:dict(j,verification='Application form found',checked_at=scout.now())):
                scout.scan()
                with scout.connect() as db:
                    db.execute("UPDATE jobs SET state='applied',notes='Follow up next week'")
                scout.scan()
                with scout.connect() as db:
                    row=db.execute('SELECT * FROM jobs').fetchone()
                    self.assertEqual(row['state'],'applied')
                    self.assertEqual(row['notes'],'Follow up next week')
                with patch('scout.board_jobs',side_effect=TimeoutError('network down')):
                    scout.scan()
                    with scout.connect() as db:
                        saved=json.loads(db.execute('SELECT payload FROM jobs').fetchone()[0])
                        self.assertNotEqual(saved['verification'],'No longer listed')
                with patch('scout.board_jobs',return_value=([],False)):
                    scout.scan()
                    with scout.connect() as db:
                        saved=json.loads(db.execute('SELECT payload FROM jobs').fetchone()[0])
                        self.assertEqual(saved['verification'],'No longer listed')

    def test_csv_formula_injection_is_neutralized(self):
        with patch('scout.snapshot',return_value={'jobs':[job(company='=WEBSERVICE("x")')]}):
            self.assertIn("'=WEBSERVICE",scout.csv_export())


if __name__ == '__main__':
    unittest.main()
