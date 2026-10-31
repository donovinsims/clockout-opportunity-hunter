import csv
import json
import tempfile
import unittest
from pathlib import Path
from opportunity_hunter import review_signals as rs
from opportunity_hunter.engine import Store, score, export

CID='0x8808b7639615b481:0xe8778d0ea2d8ce33'

def lead(**kw):
    p={'name':'Sample Electric LLC','city':'Rockford','website':'https://example.com','contacts':[{'kind':'phone','value':'(815) 555-0123','source':'https://example.com'}],
       'findings':[{'verified':True,'severity':'important','points':25,'code':'mobile_scaled_text','observation':'Text is tiny on phones.','impact':'Hard to read.','url':'https://example.com','checked_at':'2026-10-30','artifact':'a.png'}],
       'territory_verified':True,'service_evidence':{'quote':'electric service'},'independence_evidence':{'quote':'family owned','url':'https://example.com'},
       'commercial_evidence':{'quote':'free estimates','url':'https://example.com'},'closed_evidence':None,'checked_at':'2026-10-30','pages':[{'url':'https://example.com'}],
       'industry':'Electrical contractor','suggested_solution':'One-page refresh','next_action':'Owner review','unverified':[],'maps_url':f'https://www.google.com/maps/place/x/data=!4m7!3m6!1s{CID}!8m2'}
    p.update(kw);return p

def signals(**kw):
    b={'placeId':CID,'name':'Sample Electric LLC','inputUrl':'u','jobStatus':'complete','strength':'strong','reviewsScanned':40,
       'matches':[{'topic':'phone_not_answered','kind':'explicit','reviewId':'R1','dateRaw':'3 months ago','rating':1,'quote':'They never called me back.'},
                  {'topic':'had_to_call','kind':'indirect','reviewId':'R2','dateRaw':'a year ago','rating':2,'quote':'I had to call and call.'}],'businessSignals':[]}
    b.update(kw);return {'schema':'gmr-signals/2','businesses':[b]}

class ReviewSignals(unittest.TestCase):
    def tmp(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data')

    def test_joins_by_place_id_as_confirmed(self):
        s=rs.summarize(lead(),signals()['businesses'])
        self.assertEqual(s['join'],'confirmed (place id)');self.assertEqual(s['strength'],'strong')
        self.assertEqual(len(s['explicit']),1);self.assertEqual(len(s['indirect']),1)

    def test_name_and_town_fallback_is_unconfirmed(self):
        b=signals(placeId='0x1:0x2',town='Rockford')['businesses']
        s=rs.summarize(lead(maps_url=''),b);self.assertTrue(s['join'].startswith('unconfirmed'))
        b=signals(placeId='0x1:0x2',town='Belvidere')['businesses']
        self.assertIsNone(rs.summarize(lead(maps_url=''),b))

    def test_partial_or_failed_job_is_incomplete_even_with_matches(self):
        with self.tmp() as td:
            f=Path(td,'s.json');f.write_text(json.dumps(signals(jobStatus='partial')))
            b,w=rs.load(f);self.assertEqual(w,[]);s=rs.summarize(lead(),b)
            self.assertEqual(s['strength'],'incomplete');self.assertIn('do not establish absence',s['note'])
            f.write_text(json.dumps(signals(jobStatus='failed',strength='none-found',matches=[])))
            self.assertEqual(rs.load(f)[0][0]['strength'],'incomplete')

    def test_missing_or_malformed_file_warns_and_continues(self):
        with self.tmp() as td:
            self.assertIn('not found',rs.load(Path(td,'nope.json'))[1][0])
            f=Path(td,'bad.json');f.write_text('{not json');self.assertIn('unreadable',rs.load(f)[1][0])
            f.write_text('[1,2]');self.assertIn('no "businesses"',rs.load(f)[1][0])
            f.write_text(json.dumps({'businesses':[5,{'name':'X','jobStatus':'complete'}]}))
            b,w=rs.load(f);self.assertEqual(len(b),1);self.assertIn('1 malformed',w[0])

    def test_no_website_on_maps_is_indirect_only(self):
        p=lead(maps_website_search_artifact='data/evidence/x.json')
        s=rs.summarize(p,signals(strength='none-found',matches=[])['businesses'])
        self.assertEqual(s['strength'],'weak');self.assertEqual(s['business_signals'][0]['topic'],'no_website_on_maps')

    def test_export_shows_section_and_never_changes_score(self):
        with self.tmp() as td:
            root=Path(td);(root/'data/drafts').mkdir(parents=True);st=Store(root)
            p=score(lead(),{});st.upsert(p);before=json.dumps([(x['score'],x['qualified']) for x in st.all()])
            f=root/'signals.json';f.write_text(json.dumps(signals()))
            summary={};export(root,st,'r1',summary,f)
            after=json.dumps([(x['score'],x['qualified']) for x in st.all()]);self.assertEqual(before,after)
            report=(root/'data/latest-report.md').read_text()
            self.assertIn('# Review signals (informational; not part of the verified score)',report)
            self.assertIn('strength: strong',report);self.assertIn('They never called me back.',report);self.assertIn('3 months ago',report)
            rows=list(csv.DictReader((root/'data/review-signals.csv').open()))
            self.assertEqual(rows[0]['strength'],'strong');self.assertEqual(rows[0]['top_quote_review_id'],'R1')
            with (root/'data/prospects.csv').open() as fh:header=next(csv.reader(fh))
            self.assertNotIn('strength',header)
            self.assertEqual(summary['review_signals']['matched_prospects'],1);st.db.close()

    def test_export_with_missing_file_still_completes(self):
        with self.tmp() as td:
            root=Path(td);(root/'data/drafts').mkdir(parents=True);st=Store(root);st.upsert(score(lead(),{}))
            summary={};export(root,st,'r2',summary,root/'missing.json')
            self.assertTrue((root/'data/latest-report.md').exists());self.assertIn('not found',summary['review_signals']['warnings'][0]);st.db.close()

    def test_export_without_flag_is_unchanged(self):
        with self.tmp() as td:
            root=Path(td);(root/'data/drafts').mkdir(parents=True);st=Store(root);st.upsert(score(lead(),{}))
            summary={};export(root,st,'r3',summary)
            self.assertNotIn('review_signals',summary);self.assertNotIn('Review signals',(root/'data/latest-report.md').read_text())
            self.assertFalse((root/'data/review-signals.csv').exists());st.db.close()

if __name__=='__main__':unittest.main()
