"""Optional bounded Maps discovery. Selector approach adapted from GMapsLeadsPro.
See docs/third-party-notices.md. Public listing data is discovery evidence only.
"""
import json
import hashlib
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from bs4 import BeautifulSoup
from .web import now, is_challenge, domain, public_url

MAP_FIELDS = ['maps_url','google_category','google_rating','google_review_count','maps_checked_at']


def parse_listing(html, url, city, query):
    soup = BeautifulSoup(html, 'html.parser')
    name = soup.select_one('h1.DUwDvf, h1.fontHeadlineLarge, h1')
    if not name or name.get_text(strip=True).lower() in ('results','overview','google maps'):
        return None
    def field(selector, prefix=''):
        el=soup.select_one(selector)
        if not el:return ''
        value=el.get('aria-label') or el.get_text(' ',strip=True)
        return re.sub(prefix, '', value, flags=re.I).strip() if prefix else value.strip()
    authority=soup.select_one('a[data-item-id*="authority"]')
    website=authority.get('href','') if authority else ''
    if website and (urlsplit(website).scheme not in ('http','https') or domain(website)=='google.com'):website=''
    rating=None; count=None
    for el in soup.select('[aria-label]'):
        label=el['aria-label']
        m=re.fullmatch(r'\s*([0-5](?:[.,]\d+)?)\s+stars?\s*',label,re.I)
        if m:rating=float(m[1].replace(',','.'))
        m=re.fullmatch(r'\s*([\d,]+)\s+reviews?\s*',label,re.I)
        if m:count=int(m[1].replace(',',''))
    if count is None:
        for el in soup.select('button[jsaction*="reviewChart"], button[jsaction*="moreReviews"]'):
            m=re.search(r'([\d,]+)\s+reviews?',el.get_text(' ',strip=True),re.I)
            if m:count=int(m[1].replace(',',''));break
    category=field('button[jsaction*="category"]')
    pid=re.search(r'!19s([^!/?&]+)',url)
    cid=re.search(r'!1s([^!/?&]+)',url)
    return {'name':name.get_text(' ',strip=True),'city':city,'industry':category or 'service business (verify)',
            'website':website,'discovery_source':url,'maps_url':url,'maps_place_id':unquote(pid[1]) if pid else '',
            'maps_cid':unquote(cid[1]) if cid else '', 'maps_address':field('button[data-item-id="address"]',r'^Address:\s*'),
            'maps_phone':field('button[data-item-id*="phone"]',r'^Phone:\s*'),
            'google_category':category,'google_rating':rating,'google_review_count':count,
            'maps_checked_at':now(),'maps_query':query,
            'maps_field_notes':(['Google limited view; hidden review counts remain unknown'] if 'limited view of Google Maps' in soup.get_text(' ',strip=True) else []),
            'maps_closed':bool(re.search(r'permanently closed',soup.get_text(' ',strip=True),re.I))}


def discover_maps(root, query, city, limit=10, timeout=120):
    root=Path(root).resolve()
    territory=json.loads((root/'config/settings.json').read_text())['territory']
    if city not in territory:raise ValueError('City must be one of the eight approved towns')
    if not query.strip() or len(query)>200:raise ValueError('Supply a query of 1–200 characters')
    if limit<1:raise ValueError('Limit must be positive')
    folder=root/'data/maps'/uuid.uuid4().hex;folder.mkdir(parents=True)
    result={'query':query,'city':city,'checked_at':now(),'candidates':[],'errors':[],'status':'running'}
    path=folder/'result.json';path.write_text(json.dumps(result))
    started=time.monotonic()
    proc=subprocess.Popen([sys.executable,'-m','opportunity_hunter.maps',str(root),query,city,str(min(limit,10)),str(path)],
                          cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    timed_out=False
    try:proc.wait(timeout=min(timeout,120))
    except subprocess.TimeoutExpired:
        timed_out=True
    finally:
        # Also clean up descendants after an unexpected worker exit.
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait()
    result=json.loads(path.read_text())
    if timed_out:result['errors'].append('Two-minute discovery deadline reached; partial results retained')
    elif proc.returncode and result['status']=='running':result['errors'].append('Maps worker unavailable; core research remains available')
    result['status']='partial' if result['errors'] and result['candidates'] else 'failed' if result['errors'] else 'completed'
    result['elapsed_seconds']=round(time.monotonic()-started,2)
    result['artifact']=str(path.relative_to(root));path.write_text(json.dumps(result,indent=2))
    return result


def _worker(root,query,city,limit,path):
    from playwright.sync_api import sync_playwright
    result=json.loads(path.read_text())
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2));tmp.replace(path)
    try:
        with sync_playwright() as pw:
            chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            browser=pw.chromium.launch(headless=True,chromium_sandbox=True,timeout=15000,
                                      **({'executable_path':str(chrome)} if chrome.exists() else {}))
            context=browser.new_context(locale='en-US',accept_downloads=False,service_workers='block')
            # Isolated ephemeral profile: never inherits the owner's Google session.
            checked_hosts=set()
            def route_public(route):
                try:
                    req=route.request
                    if req.resource_type in ('image','media','font'):return route.abort()
                    parsed=urlsplit(req.url)
                    if parsed.scheme not in ('https','http') or parsed.username or parsed.password or parsed.port not in (None,80,443):return route.abort()
                    if parsed.hostname not in checked_hosts:
                        public_url(req.url);checked_hosts.add(parsed.hostname)
                    return route.continue_()
                except Exception:return route.abort()
            context.route('**/*',route_public)
            page=context.new_page();page.set_default_timeout(8000)
            state='WI' if city=='Beloit' else 'IL'
            search_url='https://www.google.com/maps/search/'+quote(f'{query} in {city} {state}')+'?hl=en&gl=us'
            page.goto(search_url,wait_until='domcontentloaded',timeout=25000)
            def check():
                if is_challenge(page.content()):raise ValueError('Maps access challenge; stopped without bypass')
                if page.locator('form[action*="consent"], button[aria-label="Accept all"]').count():
                    raise ValueError('Maps consent screen requires manual review')
            page.wait_for_timeout(2500);check()
            links=[]
            for scroll in range(6):
                check()
                for href in page.locator('a.hfpxzc').evaluate_all('(els)=>els.map(e=>e.href)'):
                    if href not in links and urlsplit(href).hostname in ('www.google.com','google.com') and '/maps/place/' in href:links.append(href)
                if len(links)>=limit or scroll==5:break
                feed=page.locator('div[role="feed"]')
                if not feed.count():break
                feed.first.evaluate('(e)=>e.scrollTop=e.scrollHeight');page.wait_for_timeout(1200)
            if not links and page.locator('h1.DUwDvf').count():links=[page.url]
            for idx,url in enumerate(links[:limit]):
                try:
                    page.goto(url,wait_until='domcontentloaded',timeout=15000)
                    page.wait_for_timeout(1200);check()
                    html=page.content();candidate=parse_listing(html,page.url,city,query)
                    if not candidate:raise ValueError('Listing selectors returned no business name')
                    evidence=path.parent/f'listing-{idx+1}.html';evidence.write_text(html)
                    candidate['maps_artifact']=str(evidence.relative_to(root))
                    candidate['maps_sha256']=hashlib.sha256(html.encode()).hexdigest()
                    result['candidates'].append(candidate);save()
                except Exception as e:
                    result['errors'].append('Listing '+str(idx+1)+': '+type(e).__name__+(': '+str(e) if isinstance(e,ValueError) else ''))
                    save()
                    if isinstance(e,ValueError) and ('challenge' in str(e) or 'consent' in str(e)):break
            if not links:result['errors'].append('No listing links found; results empty or page layout unsupported')
            browser.close()
    except Exception as e:result['errors'].append(type(e).__name__+(': '+str(e) if isinstance(e,ValueError) else ': browser/navigation unavailable'))
    result['status']='partial' if result['errors'] else 'completed';save()

if __name__=='__main__':
    _worker(Path(sys.argv[1]),sys.argv[2],sys.argv[3],int(sys.argv[4]),Path(sys.argv[5]))
