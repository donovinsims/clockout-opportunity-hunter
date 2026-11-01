import json
import unittest
from opportunity_hunter.maps_network import parse_entities,merge_network

class NetworkBackupTests(unittest.TestCase):
    def entity(self):
        e=[None]*179;e[11]='Local Electric';e[10]='0x1:0x2';e[78]='ChIJfixture';e[18]='12 Main St, Roscoe, IL 61073';e[7]=['https://local-electric.org'];e[13]=['Electrician'];e[178]=[['(815) 555-0123']];e[4]=[None]*9;e[4][7]=4.8;e[4][8]=45;return e
    def test_parse_real_layout_field_paths_and_dedup(self):
        e=self.entity();rows=parse_entities(")]}'\n"+json.dumps([None,[[None,e],[None,e]]]))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['google_review_count'],45);self.assertEqual(rows[0]['google_rating'],4.8)
        self.assertEqual(rows[0]['maps_phone'],'(815) 555-0123')
    def test_bad_or_missing_count_never_becomes_zero(self):
        for count in [None,True,-1,'45']:
            e=self.entity();e[4][8]=count;self.assertIsNone(parse_entities(json.dumps([e]))[0]['google_review_count'])
        self.assertEqual(parse_entities('not JSON'),[])
        self.assertEqual(parse_entities(json.dumps([[None,'not a place']])),[])
    def test_merging_requires_identity_and_does_not_override_verified_fields(self):
        row=parse_entities(json.dumps([self.entity()]))[0]
        p={'name':'Local Electric','maps_phone':'815-555-0123','google_rating':4.9,'google_review_count':None}
        merge_network(p,[row]);self.assertEqual(p['google_rating'],4.9);self.assertEqual(p['google_review_count'],45)
        other={'name':'Unrelated Electric','maps_phone':'815-555-9999','google_review_count':None}
        merge_network(other,[row]);self.assertIsNone(other['google_review_count'])
    def test_matching_name_cannot_override_conflicting_stable_identity(self):
        row=parse_entities(json.dumps([self.entity()]))[0]
        p={'name':'Local Electric','maps_phone':'815-555-0123','maps_cid':'0x9:0x9','google_review_count':None}
        merge_network(p,[row]);self.assertIsNone(p['google_review_count'])

if __name__=='__main__':unittest.main()
