import csv
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from opportunity_hunter.search import search
from opportunity_hunter.integrations import sync_sheets, sync_gmail
from opportunity_hunter.engine import Store, INDEPENDENT
import re

HEADERS=['id','name','city','industry','website','public_contacts','contact_source','website_findings','evidence_urls','verification_date','score','qualification_status','suggested_solution','outreach_angle','outreach_status','follow_up_date','next_action','last_researched']

class IntegrationBehavior(unittest.TestCase):
    def test_tavily_failure_falls_back_to_brave_without_exposing_key(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as root:
            Path(root,'.env').write_text('TAVILY_API_KEY=test-tavily-secret\nBRAVE_API_KEY=test-brave-secret\n')
            response=io.BytesIO(json.dumps({'web':{'results':[{'title':'Real search response fixture','url':'https://example.com','description':'fixture only'}]}}).encode())
            with patch('opportunity_hunter.search.urllib.request.urlopen',side_effect=[urllib.error.URLError('offline'),response]):result=search('fixture query',root)
            self.assertEqual(result['provider'],'brave');self.assertNotIn('secret',json.dumps(result));self.assertEqual(len(result['results']),1)

    def test_sheets_refresh_never_writes_owner_status_or_followup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data') as root:
            Path(root,'data').mkdir();store=Store(root)
            values={h:'' for h in HEADERS};values.update(id='p1',name='Fixture Company',qualification_status='qualified',outreach_status='not contacted')
            with Path(root,'data/prospects.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=HEADERS);w.writeheader();w.writerow(values)
            old=['p1']+['']*13+['do not contact','2026-11-06','','']
            metadata={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':26}}}]}
            with patch('opportunity_hunter.integrations.request_json',side_effect=[metadata,{'values':[HEADERS,old]},{'totalUpdatedCells':24}]) as transport:
                result=sync_sheets(root,store,'test-token','test-sheet')
            updates=transport.call_args_list[2].args[1]['data']
            ranges=[u['range'] for u in updates]
            self.assertNotIn('OpportunityHunter!O2',ranges);self.assertNotIn('OpportunityHunter!P2',ranges)
            self.assertIn('OpportunityHunter!A2',ranges);self.assertIn('OpportunityHunter!N2',ranges)
            self.assertEqual(result['status'],'working');store.db.close()

    def test_missing_google_auth_is_nonblocking(self):
        self.assertEqual(sync_gmail('.',None,None)['status'],'unconfigured')
        self.assertEqual(sync_sheets('.',None,None,None)['status'],'unconfigured')

    def test_copyright_is_not_independent_ownership(self):
        self.assertIsNone(re.search(INDEPENDENT,'The website content is owned by us and our licensors.',re.I))
        self.assertIsNotNone(re.search(INDEPENDENT,'Current owner, Gene, runs the business.',re.I))

if __name__=='__main__':unittest.main()
