import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ReviewProfileCompatibility(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node') and (ROOT/'vendor/reviews/node_modules/rebrowser-playwright').exists(),'Optional review runtime not installed')
    def test_manual_login_profile_uses_same_os_keychain_and_sandbox(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as td:
            script="""
import { launchWithFallback } from './vendor/reviews/src/collector/browser.js';
let options;
const mock={launchPersistentContext:async(profile,opts)=>{options=opts;return {};}};
await launchWithFallback(mock,process.argv[1],{},{});
console.log(JSON.stringify({sandbox:options.chromiumSandbox,ignored:options.ignoreDefaultArgs}));
"""
            result=subprocess.run(['node','--input-type=module','-e',script,td],cwd=ROOT,text=True,capture_output=True,check=True,timeout=10)
            options=json.loads(result.stdout)
            self.assertTrue(options['sandbox']);self.assertIn('--use-mock-keychain',options['ignored']);self.assertIn('--password-store=basic',options['ignored'])

class ReviewAuthTabOwnership(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node') and (ROOT/'vendor/reviews/node_modules/rebrowser-playwright').exists(),'Optional review runtime not installed')
    def test_missing_maps_tab_is_probed_and_only_owned_tab_is_closed(self):
        script="""
import { checkReviewAuth } from './opportunity_hunter/review_auth.mjs';
let visits=0,closed=0,created=0;
const p={url:()=> 'https://www.google.com/maps',goto:async url=>{if(!url.startsWith('https://www.google.com/maps'))throw Error('wrong source');visits++;},waitForFunction:async(fn,arg,opts)=>{if(arg!==null||opts.timeout!==8000)throw Error('wrong API arguments');},evaluate:async()=>({authState:'signed-in'}),close:async()=>{closed++;}};
const state=await checkReviewAuth({pages:()=>[],newPage:async()=>{created++;return p;}});
if(state!=='signed-in'||created!==1||visits!==1||closed!==1)throw Error('probe behavior failed');
visits=0;closed=0;created=0;
const reused=await checkReviewAuth({pages:()=>[p],newPage:async()=>{created++;return p;}});
if(reused!=='signed-in'||created||visits||closed)throw Error('owner tab modified');
console.log('PASS auth detection with and without an existing Maps tab');
"""
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=='__main__':unittest.main()
