import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from opportunity_hunter.review_session import endpoint
from opportunity_hunter.reviews import collect_one

ROOT=Path(__file__).resolve().parents[1]
class DedicatedSessionTests(unittest.TestCase):
    def test_only_matching_loopback_browser_endpoint_is_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as td:
            root=Path(td);profile=root/'data/profiles/opportunity-hunter';profile.mkdir(parents=True)
            (root/'data/reviews').mkdir();marker=root/'data/reviews/browser-session.json';marker.write_text(json.dumps({'profile':str(profile),'port':12345,'browser_id':'/devtools/browser/fixture-123'}))
            for host,expected in [('127.0.0.1','http://127.0.0.1:12345'),('remote.example',None)]:
                raw=json.dumps({'Browser':'Chrome/142.0','webSocketDebuggerUrl':f'ws://{host}:12345/devtools/browser/fixture-123'}).encode()
                with patch('opportunity_hunter.review_session.urllib.request.build_opener') as opener:
                    opener.return_value.open.return_value=io.BytesIO(raw)
                    self.assertEqual(endpoint(root),expected)
            marker.write_text(json.dumps({'profile':str(profile),'port':80,'browser_id':'/devtools/browser/fixture-123'}))
            with patch('opportunity_hunter.review_session.urllib.request.build_opener') as opener:
                self.assertIsNone(endpoint(root));opener.assert_not_called()
    def test_signed_in_collection_does_not_launch_or_rewrite_a_closed_profile(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as td:
            root=Path(td)
            with patch('opportunity_hunter.reviews.subprocess.Popen') as launch:
                r=collect_one(root,{'id':'fixture','name':'Local Business','maps_url':'https://www.google.com/maps/search/Local+Business'})
            self.assertEqual(r['status'],'needs_browser');launch.assert_not_called()
            self.assertFalse((root/'data/profiles').exists())

if __name__=='__main__':unittest.main()
