import tempfile
import unittest
from pathlib import Path
from opportunity_hunter.browser import Browser

class RealBrowserChecks(unittest.TestCase):
    def test_axe_confirms_unnamed_fields_but_accepts_labeled_fields(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root/'data') as tmp:
            Path(tmp,'data').mkdir()
            browser=Browser(tmp)
            try:
                self.assertIsNotNone(browser.context,browser.error)
                page=browser.context.new_page()
                page.set_content('<html lang="en"><head><title>Isolated test fixture</title><meta name="viewport" content="width=device-width"></head><body><form><input id="missing-name"><input id="missing-email" type="email"><label for="valid">Phone</label><input id="valid" type="tel"></form></body></html>')
                result=browser.accessibility(page)
                self.assertEqual(result['status'],'completed',result)
                labels=next(v for v in result['violations'] if v['id']=='label')
                targets=str([n['target'] for n in labels['nodes']])
                self.assertIn('missing-name',targets);self.assertIn('missing-email',targets);self.assertNotIn('#valid',targets)
                self.assertIn('Mobile',page.evaluate('navigator.userAgent'))
                page.close()
            finally:browser.close()

if __name__=='__main__':unittest.main()
