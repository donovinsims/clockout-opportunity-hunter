import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opportunity_hunter.engine import Store
from opportunity_hunter.integrations import sync_sheets


BASE = ['id','name','city','industry','website','public_contacts','contact_source',
        'website_findings','evidence_urls','verification_date','score',
        'qualification_status','suggested_solution','outreach_angle',
        'outreach_status','follow_up_date','next_action','last_researched']
MAPS = ['maps_url','google_category','google_rating','google_review_count',
        'maps_checked_at','public_emails','email_sources','email_verification_status']


class SheetsSchemaTests(unittest.TestCase):
    def _root(self, headers):
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'data')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'data').mkdir()
        with (root / 'data' / 'prospects.csv').open('w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=headers)
            w.writeheader()
            row = {h: '' for h in headers}
            row.update(id='p1', name='Fixture', city='Roscoe', qualification_status='qualified',
                       outreach_status='not contacted', maps_url='https://maps.google.test/p1',
                       google_rating='4.8', google_review_count='12')
            w.writerow(row)
        return root

    def test_legacy_header_gets_maps_columns_and_owner_fields_are_not_written(self):
        root = self._root(BASE + MAPS)
        store = Store(root)
        cloud = BASE + MAPS
        old = ['p1'] + [''] * 13 + ['do not contact', '2026-11-06', '', '']
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[
                meta, {'values': [BASE, old]}, {'totalUpdatedCells': 32}]) as request:
            sync_sheets(root, store, 'token', 'sheet')
        payload = request.call_args_list[2].args[1]
        ranges = [x['range'] for x in payload['data']]
        self.assertIn('OpportunityHunter!S1:Z1', ranges)
        self.assertNotIn('OpportunityHunter!O2', ranges)
        self.assertNotIn('OpportunityHunter!P2', ranges)
        self.assertIn('OpportunityHunter!S2', ranges)
        store.db.close()

    def test_reordered_header_and_extra_column_are_preserved(self):
        headers = ['id', 'owner_note'] + [x for x in BASE if x not in ('id','outreach_status','follow_up_date')] + ['outreach_status','follow_up_date'] + MAPS
        root = self._root(BASE + MAPS)
        store = Store(root)
        old = ['p1', 'keep'] + [''] * (len(headers)-2)
        old[headers.index('name')] = 'Fixture';old[headers.index('outreach_status')] = 'contacted';old[headers.index('follow_up_date')] = 'tomorrow';old[headers.index('qualification_status')] = 'qualified'
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[
                meta, {'values': [headers, old]}, {'totalUpdatedCells': 24}]) as request:
            sync_sheets(root, store, 'token', 'sheet')
        updates = request.call_args_list[2].args[1]['data']
        owner_cols = {chr(65 + headers.index(x)) + '2' for x in ('outreach_status','follow_up_date')}
        self.assertTrue(owner_cols.isdisjoint(set(u['range'] for u in updates)))
        self.assertIn('OpportunityHunter!C2', [u['range'] for u in updates])
        store.db.close()

    def test_duplicate_cloud_header_stops_before_write(self):
        root = self._root(BASE + MAPS)
        store = Store(root)
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[meta, {'values': [['id', 'id']]}]) as request:
            with self.assertRaisesRegex(RuntimeError, 'duplicate'):
                sync_sheets(root, store, 'token', 'sheet')
        self.assertEqual(request.call_count, 2)
        store.db.close()

    def test_blank_header_with_data_is_not_reused(self):
        root = self._root(BASE + MAPS)
        store = Store(root)
        headers = BASE + [''] + MAPS
        old = ['p1'] + [''] * (len(headers) - 1)
        old[len(BASE)] = 'keep-this'
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[meta, {'values':[headers, old]}, {'totalUpdatedCells':24}]) as request:
            sync_sheets(root, store, 'token', 'sheet')
        ranges=[u['range'] for u in request.call_args_list[2].args[1]['data']]
        self.assertNotIn('OpportunityHunter!S2', ranges)
        store.db.close()

    def test_missing_base_cloud_header_stops(self):
        root = self._root(BASE + MAPS)
        store = Store(root)
        cloud=[x for x in BASE+MAPS if x != 'website']
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[meta, {'values':[cloud]}]):
            with self.assertRaisesRegex(RuntimeError, 'missing required'):
                sync_sheets(root, store, 'token', 'sheet')
        store.db.close()

    def test_partial_positive_cell_update_is_rejected(self):
        root=self._root(BASE+MAPS);store=Store(root)
        self.addCleanup(store.db.close)
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':26}}}]}
        with patch('opportunity_hunter.integrations.request_json',side_effect=[meta,{'values':[BASE+MAPS]},{'totalUpdatedCells':1}]):
            with self.assertRaisesRegex(RuntimeError,'incomplete'):sync_sheets(root,store,'token','sheet')

    def test_duplicate_cloud_identity_stops_before_write(self):
        root=self._root(BASE+MAPS);store=Store(root)
        self.addCleanup(store.db.close)
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':26}}}]}
        with patch('opportunity_hunter.integrations.request_json',side_effect=[meta,{'values':[BASE+MAPS,['p1'],['p1']]}]) as request:
            with self.assertRaisesRegex(RuntimeError,'Duplicate IDs'):sync_sheets(root,store,'token','sheet')
        self.assertEqual(request.call_count,2)

    def test_zero_cell_update_is_rejected(self):
        root = self._root(BASE + MAPS)
        store = Store(root)
        meta={'sheets':[{'properties':{'title':'OpportunityHunter','gridProperties':{'rowCount':1000,'columnCount':40}}}]}
        with patch('opportunity_hunter.integrations.request_json', side_effect=[meta, {'values':[BASE+MAPS]}, {'totalUpdatedRows':0, 'totalUpdatedCells':0}]) as request:
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                sync_sheets(root, store, 'token', 'sheet')
        store.db.close()


if __name__ == '__main__':
    unittest.main()
