"""Optional unattended audit using the existing Chrome binary in an isolated project profile.
The desktop computer-use plugin has no standalone CLI interface; this makes repeat runs possible.
"""
import json
import re
from pathlib import Path
from .web import public_url, now

MEASURE = """() => {
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 const texts=[];let node;
 while(node=walker.nextNode()) {const e=node.parentElement;if(node.textContent.trim().length>8 && e && !['SCRIPT','STYLE','NOSCRIPT'].includes(e.tagName) && e.getBoundingClientRect().width>0 && getComputedStyle(e).visibility!=='hidden') texts.push(e);}
 const scale=Math.min(1,390/window.innerWidth);
 return {user_agent:navigator.userAgent, layout_width:window.innerWidth, document_width:document.documentElement.scrollWidth,
  client_width:document.documentElement.clientWidth, device_width:390,
  small_text_count:texts.filter(e=>parseFloat(getComputedStyle(e).fontSize)*scale<10).length,
  text_sample:texts.slice(0,20).map(e=>e.innerText.slice(0,120)),
  title:document.title, text:document.body.innerText,
  phone_links:[...document.querySelectorAll('a[href^="tel:"]')].map(e=>({text:e.innerText,href:e.getAttribute('href')})),
  email_links:[...document.querySelectorAll('a[href^="mailto:"]')].map(e=>({text:e.innerText,href:e.getAttribute('href')})),
  links:[...document.querySelectorAll('a[href]')].map(e=>({label:e.innerText,url:e.href})),
  viewport:document.querySelector('meta[name="viewport"]')?.content || null,
  unlabeled_fields:[...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]),textarea,select')]
    .filter(e=>e.getBoundingClientRect().width>0 && !e.labels?.length && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby') && !e.getAttribute('title')).length};
}"""


class Browser:
    def __init__(self, root):
        self.root = Path(root)
        self.pw = self.context = None
        self.error = None
        try:
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            opts = {'executable_path': chrome} if Path(chrome).exists() else {}
            self.context = self.pw.chromium.launch_persistent_context(
                str(self.root/'data/browser-profile'), headless=True, viewport={'width':390,'height':844},
                is_mobile=True, device_scale_factor=1, service_workers='block', accept_downloads=False,
                user_agent='Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36',
                chromium_sandbox=True, timeout=15000, **opts)
            self.context.route('**/*', self._route)
        except Exception as e:
            self.error = f'{type(e).__name__}: browser unavailable'

    def _route(self, route):
        try:
            req = route.request
            if req.method not in ('GET', 'HEAD'):
                return route.abort()
            public_url(req.url)
            return route.continue_()
        except Exception:
            return route.abort()

    def accessibility(self, page):
        library=Path(__file__).resolve().parent.parent/'node_modules/axe-core/axe.min.js'
        if not library.exists():
            return {'status':'unconfigured','reason':'Approved local axe-core dependency is unavailable'}
        try:
            page.add_script_tag(path=str(library))
            return page.evaluate("""async () => {
              const r=await axe.run(document,{runOnly:{type:'rule',values:['label','button-name','link-name','color-contrast']},
                resultTypes:['violations','incomplete'],iframes:false});
              const compact=v=>({id:v.id,impact:v.impact,help:v.help,help_url:v.helpUrl,
                nodes:v.nodes.map(n=>{let e;try{e=document.querySelector(n.target[0]);}catch(_){}
                  return {target:n.target,html:n.html.slice(0,600),summary:n.failureSummary,
                    text:e?.textContent?.trim().slice(0,150)||'',in_footer:!!e?.closest('footer,[role=contentinfo],[id*=footer i],[class*=footer i]') || /(?:powered|designed|website) by/i.test(e?.textContent||''),
                    in_form:!!e?.closest('form'),checks:[...n.any,...n.all,...n.none].map(c=>({id:c.id,data:c.data}))};})});
              return {status:'completed',engine:r.testEngine,violations:r.violations.map(compact),incomplete:r.incomplete.map(compact)};
            }""")
        except Exception as e:
            return {'status':'unverified','reason':type(e).__name__+' during axe-core scan'}

    def audit(self, url, key):
        result = {'url':url, 'checked_at':now(), 'method':'Chrome mobile emulation 390x844, GET only', 'verified':False}
        if not self.context:
            return dict(result, error=self.error)
        page = self.context.new_page()
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=15000)
            try:
                page.wait_for_load_state('networkidle',timeout=5000)
            except Exception:
                result['load_note']='Network did not become idle; performance is unverified. DOM checks continue.'
            if not response or response.status >= 400:
                raise ValueError('Browser request did not return a successful page')
            measurement = page.evaluate(MEASURE)
            if re.search(r'verify (?:that )?you are human|unusual traffic|checking your browser|access denied', measurement['text'][:1500], re.I):
                raise ValueError('Access challenge; no audit conclusion')
            result.update(measurement, verified=True, status=response.status, final_url=page.url)
            result['accessibility']=self.accessibility(page)
            dest = self.root/'data/evidence'/f'{key}-mobile.png'
            page.screenshot(path=str(dest), full_page=True, timeout=10000)
            result['screenshot'] = str(dest.relative_to(self.root))
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {str(e)[:150]}'
        finally:
            page.close()
        path = self.root/'data/evidence'/f'{key}-browser.json'
        path.write_text(json.dumps(result, indent=2))
        result['artifact'] = str(path.relative_to(self.root))
        return result

    def close(self):
        if self.context:
            self.context.close()
        if self.pw:
            self.pw.stop()
