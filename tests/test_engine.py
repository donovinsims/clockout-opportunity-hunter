import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from opportunity_hunter.engine import Store, score, safe_cell,address_pattern
from opportunity_hunter.web import public_url, domain, parse_page,is_challenge


def lead():
    return {'name':'Sample Electric LLC','city':'Rockford','website':'https://example.com','contacts':[{'kind':'phone','value':'(815) 555-0123'}],
            'findings':[{'verified':True,'severity':'important','points':25}], 'territory_verified':True,'service_evidence':{'quote':'electric service'},
            'independence_evidence':{'quote':'family owned'},'commercial_evidence':{'quote':'free estimates'},'closed_evidence':None,'checked_at':'2026-10-30'}

class Behavior(unittest.TestCase):
    def test_service_area_is_not_a_business_address(self):
        import re
        self.assertIsNone(re.search(address_pattern('Rockford'),'We serve Rockford, IL and nearby towns.',re.I))
        self.assertIsNotNone(re.search(address_pattern('Rockford'),'9290 Easton View Court, Rockford, Illinois 61107',re.I))
        self.assertIsNone(re.search(address_pattern('Rockford'),'1870 Post Rd Beloit, WI 53511',re.I))
        self.assertIsNone(re.search(address_pattern('Beloit'),'1870 Post Rd Beloit, IL 53511',re.I))

    def test_qualification_requires_real_problem_and_independence(self):
        p=lead();score(p,{});self.assertTrue(p['qualified']);self.assertEqual(p['score']['total'],82)
        p['findings'][0]['verified']=False;score(p,{});self.assertFalse(p['qualified'])
        p=lead();p['independence_evidence']=None;score(p,{});self.assertFalse(p['qualified'])

    def test_repeated_problem_across_pages_is_not_double_scored(self):
        p=lead();p['findings'][0]['code']='mobile_scaled_text'
        p['findings'].append(dict(p['findings'][0]));score(p,{})
        self.assertEqual(p['score']['website_problem'],25)

    def test_directory_is_never_a_qualified_business(self):
        p=lead();p['website']='https://www.expertise.com/home-improvement';score(p,{})
        self.assertFalse(p['qualified'])

    def test_closed_or_outside_territory_never_qualifies(self):
        for key,value in [('closed_evidence',{'quote':'permanently closed'}),('territory_verified',False)]:
            p=lead();p[key]=value;score(p,{});self.assertFalse(p['qualified'])

    def test_cross_run_identity_preserves_human_sales_status(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            Path(td,'data').mkdir();s=Store(td);p=score(lead(),{});pid,_=s.upsert(p)
            s.db.execute('UPDATE prospects SET outreach_status=?,follow_up_date=? WHERE id=?',('do not contact','2026-11-01',pid));s.db.commit()
            p=score(lead(),{});p['name']='SAMPLE Electric, L.L.C.';p['website']='http://www.example.com/contact';p['contacts'][0]['value']='+1-815-555-0123'
            new,status=s.upsert(p);self.assertEqual(new,pid);self.assertEqual(status,'updated existing');self.assertEqual(len(s.all()),1)
            self.assertEqual(s.all()[0]['outreach_status'],'do not contact');self.assertEqual(s.all()[0]['follow_up_date'],'2026-11-01');s.db.close()

    def test_private_and_credential_urls_rejected(self):
        for url in ['file:///etc/passwd','http://user:secret@example.com','http://127.0.0.1','http://169.254.169.254/latest/meta-data/']:
            with self.assertRaises(ValueError):public_url(url)

    def test_csv_formula_injection_and_canonical_domain(self):
        self.assertEqual(safe_cell('=IMPORTXML("evil")')[0],"'")
        self.assertEqual(domain('https://www.Example.com/path'),'example.com')

    def test_recaptcha_script_is_not_an_access_challenge_or_contact(self):
        html='<title>Local services</title><script src="recaptcha.js">icons@2x.png</script><p>icons@2x.png</p><a href="mailto:office@clockout.us">Email</a>'
        self.assertFalse(is_challenge(html))
        self.assertEqual(parse_page({'html':html,'url':'https://example.com'})['emails'],['office@clockout.us'])
        self.assertTrue(is_challenge('<title>Just a moment...</title><p>Verify you are human</p>'))

    def test_encoded_template_fragments_are_not_navigation_urls(self):
        page={'url':'https://example.com/','html':"<a href='\\\"/contact\\\"'>Template fragment</a><a href='/contact'>Contact</a>"}
        self.assertEqual(parse_page(page)['links'],[{'label':'Contact','url':'https://example.com/contact'}])

    def test_shared_contact_does_not_merge_different_businesses(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            Path(td,'data').mkdir();s=Store(td);pid,_=s.upsert(score(lead(),{}))
            p=lead();p['name']='Another Real Electric';p['website']='https://another.example';score(p,{})
            other,_=s.upsert(p);self.assertNotEqual(other,pid);self.assertEqual(len(s.all()),2);self.assertFalse(p['qualified']);s.db.close()

if __name__=='__main__':unittest.main()
