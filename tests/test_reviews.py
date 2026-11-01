import json
import tempfile
import unittest
from pathlib import Path
from opportunity_hunter.reviews import review_signals, identity_matches, attach_research, collect_one, write_report
from opportunity_hunter.engine import Store

class ReviewResearchTests(unittest.TestCase):
    def test_only_direct_negative_reports_are_surfaced(self):
        records=[{'reviewId':'r1','reviewText':'They never called me back.','reviewUrl':'https://www.google.com/maps/reviews/r1','rating':1},
                 {'reviewId':'r2','reviewText':'They always called me back.','rating':5},
                 {'reviewId':'r3','reviewText':'Their website is not broken.','rating':5},
                 {'reviewId':'r4','reviewText':'Another company never called me back.','rating':1},
                 {'reviewId':'r5','reviewText':'Their website is broken.','textTruncated':True}]
        found=review_signals(records)
        self.assertEqual(len(found),1);self.assertEqual(found[0]['review_id'],'r1')
        self.assertIn('corroboration',found[0]['status'])

    def test_wrong_place_is_not_accepted_even_with_matching_name(self):
        p={'name':'Local Electric LLC','maps_cid':'0x1:0x2'}
        self.assertFalse(identity_matches(p,{'name':'Local Electric','placeId':'0x1:0x3'}))
        self.assertTrue(identity_matches(p,{'name':'Local Electric','placeId':'0x1:0x2'}))
        self.assertFalse(identity_matches(p,{'name':'Unrelated Plumber','placeId':'0x1:0x2'}))
        self.assertFalse(identity_matches(p,{'name':'Local Electric'}))

    def test_review_enrichment_preserves_qualification_human_fields_and_dedupes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            root=Path(td);(root/'data').mkdir();store=Store(root);self.addCleanup(store.db.close)
            p={'name':'Local Electric','city':'Roscoe','website':'https://local-electric.org','contacts':[], 'qualified':True,'qualification_reasons':[], 'findings':[{'observation':'Phone overflow','verified':True}], 'score':{'total':80},'suggested_solution':'Fix phone layout'}
            pid,_=store.upsert(p)
            store.db.execute("UPDATE prospects SET outreach_status='replied',follow_up_date='2026-11-04' WHERE id=?",(pid,));store.db.commit()
            r={'identity_verified':True,'status':'collected','reviews':[{'reviewId':'r1','reviewText':'Never called me back.'}],'signals':[]}
            attach_research(store,p,r);attach_research(store,p,r)
            row=store.all()[0]
            self.assertTrue(row['qualified']);self.assertEqual(row['score']['total'],80);self.assertEqual(row['findings'],p['findings'])
            self.assertEqual(row['outreach_status'],'replied');self.assertEqual(row['follow_up_date'],'2026-11-04');self.assertEqual(len(row['review_records']),1)
            r['identity_verified']=False;r['status']='needs_login';r['reviews']=[]
            attach_research(store,p,r)
            fresh=dict(p);fresh.pop('review_research',None);store.upsert(fresh)
            row=store.all()[0];self.assertEqual(row['review_research']['status'],'collected');self.assertEqual(row['review_last_attempt']['status'],'needs_login')

    def test_missing_maps_source_is_nonblocking_and_reported_as_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as td:
            root=Path(td);(root/'data').mkdir()
            result=collect_one(root,{'id':'fixture','name':'No Maps URL'})
            self.assertEqual(result['status'],'unavailable');self.assertFalse(result['identity_verified'])
            text=write_report(root,[result]).read_text();self.assertIn('no conclusion',text)
            self.assertNotIn('No keyword matches',text)

if __name__=='__main__':unittest.main()
