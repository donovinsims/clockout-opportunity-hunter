import unittest
import json
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from opportunity_hunter.maps import parse_listing, discover_maps
from opportunity_hunter.enrichment import classify, outreach_angle, email_fields, readable_findings, valid_email
from opportunity_hunter.web import parse_page

class MapsTests(unittest.TestCase):
    def test_deadline_preserves_partial_results_and_kills_worker_group(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            root=Path(td);(root/'config').mkdir();(root/'config/settings.json').write_text(json.dumps({'territory':['Roscoe']}))
            proc=MagicMock(pid=999999,returncode=-9)
            proc.wait.side_effect=[subprocess.TimeoutExpired('probe',0),None]
            def launch(args,**kwargs):
                path=Path(args[-1]);data=json.loads(path.read_text());data['candidates']=[{'name':'Partial listing'}];path.write_text(json.dumps(data));return proc
            with patch('opportunity_hunter.maps.subprocess.Popen',side_effect=launch),patch('opportunity_hunter.maps.os.killpg') as kill:
                result=discover_maps(root,'electricians','Roscoe',timeout=0.01)
            self.assertEqual(result['status'],'partial');self.assertEqual(len(result['candidates']),1);kill.assert_called_once()
            with self.assertRaises(ValueError):discover_maps(root,'electricians','Winnebago')

    def test_no_website_and_high_rating_do_not_qualify(self):
        from opportunity_hunter.engine import audit
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            root=Path(td);(root/'data/evidence').mkdir(parents=True)
            fetcher=MagicMock(root=root)
            fetcher.fetch.return_value={'url':'','error':'Missing public website'}
            candidate={'name':'Unknown Electric','city':'Roscoe','website':'','maps_url':'https://www.google.com/maps/place/example','google_rating':5.0,'google_review_count':500,'google_category':'Electrician'}
            p=audit(candidate,fetcher,None,{'territory':['Roscoe'],'max_pages_per_business':4},'fixture')
            self.assertFalse(p['qualified']);self.assertEqual(p['findings'],[]);self.assertEqual(p['google_rating'],5.0)
            self.assertIn('Research only',p['outreach_angle'])

    def test_listing_collects_category_ratings_and_evidence(self):
        p=parse_listing('''<h1 class="DUwDvf">Local Electric</h1><button data-item-id="address" aria-label="Address: 123 Main St, Roscoe, IL 61073"></button><button data-item-id="phone:tel" aria-label="Phone: (815) 555-0123"></button><a data-item-id="authority" href="https://local-electric.org/"></a><button jsaction="pane.rating.category">Electrician</button><span role="img" aria-label="4.8 stars "></span><button aria-label="1,234 reviews"></button>''','https://www.google.com/maps/place/test/data=!19sChIJabc','Roscoe','electricians')
        self.assertEqual(p['google_review_count'],1234);self.assertEqual(p['google_rating'],4.8)
        self.assertEqual(p['google_category'],'Electrician');self.assertEqual(p['maps_place_id'],'ChIJabc')
        self.assertEqual(p['maps_phone'],'(815) 555-0123')
    def test_missing_rating_count_and_site_are_unknown(self):
        p=parse_listing('<h1>Business</h1>','https://www.google.com/maps/place/test','Rockton','auto repair')
        self.assertIsNone(p['google_rating']);self.assertIsNone(p['google_review_count']);self.assertEqual(p['website'],'')
        self.assertIsNone(parse_listing('<h1>Results</h1>','x','Rockton','x'))
    def test_count_text_fallback_and_explicit_zero(self):
        p=parse_listing('<h1>Business</h1><button jsaction="pane.reviewChart.moreReviews">0 reviews</button>','x','Rockton','x')
        self.assertEqual(p['google_review_count'],0)
    def test_email_filter_and_mailto_decoding(self):
        for email in ['icons@2x.png','test@example.com','junk','name@domain.com']:
            self.assertFalse(valid_email(email))
        parsed=parse_page({'url':'https://clockout.us','html':'<a href="mailto:Office%40clockout.us?subject=Hi">Email</a>'})
        self.assertEqual(parsed['emails'],['office@clockout.us'])
        fields=email_fields({'contacts':[{'kind':'email','value':'office@clockout.us','source':'https://clockout.us/contact'}]})
        self.assertIn('deliverability',fields['email_verification_status'])
    def test_industry_conflict_and_distinct_grounded_angle(self):
        p={'name':'Local Plumber','google_category':'Electrician','unverified':[],'findings':[{'verified':True,'severity':'important','code':'mobile_overflow','observation':'Page overflows at phone width.','impact':'Harder to reach contacts.','url':'https://clockout.us','checked_at':'2026-10-30'}]}
        classify(p,'Our licensed plumbers provide plumbing services.')
        self.assertEqual(p['industry'],'Plumbing');self.assertIn('conflict',p['unverified'][0])
        self.assertIn('Local Plumber',outreach_angle(p));self.assertIn('Evidence:',readable_findings(p))
        self.assertIn('Research only',outreach_angle({'name':'No issue','findings':[]}))

if __name__=='__main__':unittest.main()
