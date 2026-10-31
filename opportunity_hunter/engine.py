import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urljoin, unquote
from .web import Fetcher, parse_page, domain, excerpt, now,directory_url
from .browser import Browser
from .enrichment import FIELDS, classify, outreach_angle, readable_findings, email_fields, valid_email

SERVICE = r'plumb|electric|roof|landscap|lawn|tree|auto|repair|heating|cooling|HVAC|glass|cleaning|garage|paving|concrete|excavat|paint|floor|carpet|septic|remodel'
INDEPENDENT = r'family[ -](?:owned|operated|business)|locally[ -](?:owned|operated)|owner[ -]operated|independently[ -]owned|veteran[ -]owned|founded by|current owner[, :]|(?:second|third|fourth) generation in our family'
COMMERCIAL = r'free (?:estimate|quote)|request (?:a |an )?(?:estimate|quote)|call (?:us|today)|business hours|Monday|Mon\s*[-–]|since (?:19|20)\d{2}|licensed|residential and commercial|\d+\s+years in business|24 hour emergency'
CLOSED = r'permanently closed|no longer in business|ceased operations'
FRANCHISE = r'\bfranchis(?:e|es|ing)\b|\bRoto.Rooter\b|\bMr\. Rooter\b|\bCARSTAR\b|\bTuffy\b'


def address_pattern(city):
    # A service-area mention is not a business location. Require a street address,
    # matching city/state and ZIP in the business-controlled content.
    state=r'(?:WI|Wisconsin)' if city=='Beloit' else r'(?:IL|Illinois)'
    return (r'\b\d{1,6}\s+[\w .#-]{2,80}?\b(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Lane|Ln|Boulevard|Blvd|Way|Highway|Hwy|Parkway|Pkwy|Trail|Trl|Place|Pl|Circle|Cir)\.?[, ]*'
            +re.escape(city)+r'\s*,?\s*'+state+r'\s*\d{5}\b')


def normal(s):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', s).lower())


def phone_key(s):
    return re.sub(r'\D', '', s)[-10:]


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.db = sqlite3.connect(self.root/'data/hunter.sqlite3')
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS prospects(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
          outreach_status TEXT NOT NULL DEFAULT 'not contacted', follow_up_date TEXT NOT NULL DEFAULT '', updated_at TEXT);
        CREATE TABLE IF NOT EXISTS identities(kind TEXT, value TEXT, prospect_id TEXT REFERENCES prospects(id), PRIMARY KEY(kind,value));
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, status TEXT, started_at TEXT, finished_at TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS integration_receipts(kind TEXT, local_id TEXT, remote_id TEXT, PRIMARY KEY(kind,local_id));
        ''')

    def keys(self, p):
        keys = [('name_city', normal(p['name'])+':'+normal(p['city']))]
        if domain(p.get('website','')):
            keys.append(('domain', domain(p['website'])))
        if p.get('maps_place_id'):keys.append(('maps_place_id',p['maps_place_id']))
        keys += [('phone', phone_key(c['value'])) for c in p.get('contacts',[]) if c['kind']=='phone' and len(phone_key(c['value']))==10]
        keys += [('email', c['value'].lower()) for c in p.get('contacts',[]) if c['kind']=='email' and c['value'].rsplit('.',1)[-1].lower() not in ('png','jpg','svg','webp','gif','js','css')]
        return list(dict.fromkeys(keys))

    def review_hold(self,p):
        file=self.root/'data/review-holds.json'
        holds=json.loads(file.read_text()) if file.exists() else {}
        hold=holds.get(domain(p.get('website','')))
        if hold:
            p['qualified']=False;p['review_hold']=hold
            reason='Review hold: '+hold
            if reason not in p['qualification_reasons']:p['qualification_reasons'].append(reason)
        if p.get('outreach_status')=='do not contact':
            p['qualified']=False
            if 'Owner marked do not contact' not in p['qualification_reasons']:p['qualification_reasons'].append('Owner marked do not contact')
        return p

    def upsert(self, p):
        self.review_hold(p)
        matches = set(); contact_matches=set()
        for k,v in self.keys(p):
            row = self.db.execute('SELECT prospect_id FROM identities WHERE kind=? AND value=?',(k,v)).fetchone()
            if row:
                (matches if k in ('domain','name_city','maps_place_id') else contact_matches).add(row[0])
        if contact_matches-matches:
            p['identity_warning']='Public contact overlaps another business; verify ownership before outreach.'
            p['qualified']=False
            p['qualification_reasons'].append(p['identity_warning'])
        if len(matches)>1:
            p['qualified']=False
            p['qualification_reasons'].append('Conflicting existing identities; manual review required')
            return None, 'identity conflict'
        pid = next(iter(matches), hashlib.sha256((normal(p['name'])+normal(p['city'])).encode()).hexdigest()[:16])
        if not matches and self.db.execute('SELECT 1 FROM prospects WHERE id=?',(pid,)).fetchone():
            pid=hashlib.sha256((pid+p['website']).encode()).hexdigest()[:16]
        duplicate = bool(matches)
        human=self.db.execute('SELECT outreach_status FROM prospects WHERE id=?',(pid,)).fetchone()
        if human and human[0]=='do not contact':
            p['qualified']=False;p['qualification_reasons'].append('Owner marked do not contact')
        p['id'] = pid
        old=self.db.execute('SELECT payload FROM prospects WHERE id=?',(pid,)).fetchone()
        if old:
            for k,v in json.loads(old[0]).items():
                if k.startswith(('maps_','google_')) and k not in p:p[k]=v
        # Existing human outreach fields live outside the researched payload and are never overwritten.
        with self.db:
            self.db.execute('INSERT INTO prospects(id,payload,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at', (pid,json.dumps(p),now()))
            for k,v in self.keys(p):
                self.db.execute('INSERT OR IGNORE INTO identities VALUES(?,?,?)',(k,v,pid))
        return pid, 'updated existing' if duplicate else 'created'

    def all(self):
        rows=[]
        for payload,status,follow in self.db.execute('SELECT payload,outreach_status,follow_up_date FROM prospects'):
            p=json.loads(payload);p.update(outreach_status=status,follow_up_date=follow);rows.append(self.review_hold(p))
        return sorted(rows,key=lambda p:p['score']['total'],reverse=True)


def score(p, settings):
    verified=[f for f in p['findings'] if f['verified'] and f['severity'] in ('important','blocker')]
    points={}
    for i,f in enumerate(p['findings']):
        if f['verified'] and (f['severity'] in ('important','blocker') or (verified and f['severity']=='supporting')):
            code=f.get('code','finding-'+str(i));points[code]=max(points.get(code,0),f['points'])
    severity=min(35,sum(points.values()))
    fit=(5 if p['territory_verified'] else 0)+(15 if p['service_evidence'] else 0)+(5 if p['independence_evidence'] else 0)
    kinds={x['kind'] for x in p['contacts']}
    contact=min(20,(12 if 'phone' in kinds else 0)+(8 if 'email' in kinds else 0)+(6 if 'form' in kinds else 0))
    commercial=(10 if p['service_evidence'] else 0)+(10 if p['commercial_evidence'] else 0)
    result={'website_problem':severity,'business_fit':fit,'contact_accessibility':contact,'commercial_opportunity':commercial,'total':severity+fit+contact+commercial}
    reasons=[]
    for condition,reason in [(result['total']>=70,'Score below 70'),(bool(verified),'No verified meaningful website problem'),
                            (p['territory_verified'],'Location outside territory or unverified'),(bool(p['independence_evidence']),'Independent ownership unverified'),
                            (bool(p['service_evidence'] and p['commercial_evidence']),'Commercial activity evidence insufficient'),
                            (bool(kinds),'No verified public contact channel'),(not p['closed_evidence'],'Closure signal requires review')]:
        if not condition:reasons.append(reason)
    if p.get('franchise_evidence'):reasons.append('Franchise signal requires exclusion or manual verification')
    if directory_url(p.get('website','')):reasons.append('Directory/social listing is a discovery source, not a verified official business website')
    p.update(score=result,qualified=not reasons,qualification_reasons=reasons)
    return p


def resolve_website(candidate,fetcher):
    """Missing Maps website is unknown. Accept only a phone-matched public site."""
    if candidate.get('website') or not candidate.get('maps_phone'):return candidate
    from .search import search
    research=search(candidate['name']+' '+candidate['maps_phone']+' '+candidate['city']+' official website',fetcher.root)
    checked=fetcher.root/'data/evidence'/('website-search-'+hashlib.sha256((candidate['name']+now()).encode()).hexdigest()[:20]+'.json')
    checked.parent.mkdir(parents=True,exist_ok=True);checked.write_text(json.dumps(research,indent=2))
    candidate=dict(candidate)
    candidate['maps_website_search_artifact']=str(checked.relative_to(fetcher.root))
    for item in research['results'][:5]:
        if directory_url(item['url']):continue
        raw=fetcher.fetch(item['url'])
        if raw.get('error'):continue
        parsed=parse_page(raw)
        tokens=[w for w in re.findall(r'[a-z]+',candidate['name'].lower()) if len(w)>2 and w not in ('inc','llc','company','services')]
        if (any(phone_key(v)==phone_key(candidate['maps_phone']) for v in parsed['phones'])
            and tokens and sum(w in parsed['text'].lower() for w in tokens)>=min(2,len(tokens))):
            candidate['website']=raw['url'];break
    return candidate


def audit(candidate, fetcher, browser, settings, run_id):
    candidate=resolve_website(candidate,fetcher)
    p={k:candidate.get(k,'') for k in ('name','city','industry','website','discovery_source')}
    for k,v in candidate.items():
        if k.startswith(('maps_', 'google_')):p[k]=v
    p.update(checked_at=now(),contacts=[],findings=[],pages=[],unverified=['Real-user performance/Core Web Vitals','Form delivery (no submissions)','Owner budget, timing and buying intent','Full accessibility compliance','Search ranking'])
    page=fetcher.fetch(p['website']); pages=[page]
    if not page.get('error'):
        parsed=parse_page(page)
        more=[]
        for link in parsed['links']:
            if domain(link['url'])==domain(page['url']) and re.search(r'contact|about|service',link['label']+' '+link['url'],re.I):
                if link['url'] not in more and link['url']!=page['url'] and not urlsplit(link['url']).fragment:
                    more.append(link['url'])
        more.sort(key=lambda u: (0 if re.search('contact',u,re.I) else 1 if re.search('about',u,re.I) else 2))
        pages += [fetcher.fetch(u) for u in more[:settings['max_pages_per_business']-1]]
    texts=[]
    for raw in pages:
        meta={k:v for k,v in raw.items() if k!='html'}
        p['pages'].append(meta)
        if raw.get('error'):continue
        parsed=parse_page(raw);texts.append((raw,parsed))
        for kind,values in [('phone',parsed['phones']),('email',parsed['emails'])]:
            for v in values:
                if not any(c['kind']==kind and (phone_key(c['value'])==phone_key(v) if kind=='phone' else c['value']==v) for c in p['contacts']):
                    p['contacts'].append({'kind':kind,'value':v,'source':raw['url'],'artifact':raw['artifact']})
    p.update(territory_verified=False,service_evidence=None,independence_evidence=None,commercial_evidence=None,closed_evidence=None,franchise_evidence=None)
    for raw,parsed in texts:
        def evidence(pattern):
            q=excerpt(parsed['text'],pattern)
            return {'quote':q,'url':raw['url'],'artifact':raw['artifact'],'checked_at':raw['checked_at']} if q else None
        locations=[(city,evidence(address_pattern(city))) for city in settings['territory']]
        locations=[x for x in locations if x[1]]
        if locations:
            city,location=next((x for x in locations if x[0]==p['city']),locations[0])
            p['city']=city;p['territory_verified']=True;p['location_evidence']=location
        p['service_evidence']=p['service_evidence'] or evidence(SERVICE)
        p['independence_evidence']=p['independence_evidence'] or evidence(INDEPENDENT)
        p['commercial_evidence']=p['commercial_evidence'] or evidence(COMMERCIAL)
        p['closed_evidence']=p['closed_evidence'] or evidence(CLOSED)
        p['franchise_evidence']=p['franchise_evidence'] or evidence(FRANCHISE)
    if texts and browser:
        targets=[page]
        contact=next((raw for raw,parsed in texts if raw['url']!=page['url'] and re.search(r'contact|quote|estimate',raw['url'],re.I)),None)
        if contact:targets.append(contact)
        p['browser_checks']=[]
        for browser_source in targets:
            audit_url=browser_source['url']
            key=hashlib.sha256((run_id+p['website']).encode()).hexdigest()[:20]
            b=browser.audit(audit_url,key);p['browser_checks'].append(b);p.setdefault('browser',b)
            if b['verified']:
                if len(targets)==1:
                    links=[l for l in b.get('links',[]) if domain(l['url'])==domain(audit_url) and not re.search(r'[\\"<>\s]',l['url']) and not urlsplit(l['url']).fragment and re.search(r'contact|quote|estimate',l['url'],re.I)]
                    if links:
                        contact=fetcher.fetch(links[0]['url'])
                        if not any(x['url']==contact['url'] for x in p['pages']):p['pages'].append({k:v for k,v in contact.items() if k!='html'})
                        if not contact.get('error') and contact['url']!=audit_url:targets.append(contact)
                # Use the rendered business content as well as static HTML. Some sites put
                # their actual copy/contact links in JavaScript templates.
                rendered=b.get('text','')
                def rendered_evidence(pattern):
                    q=excerpt(rendered,pattern)
                    return {'quote':q,'url':audit_url,'artifact':b['artifact'],'checked_at':b['checked_at']} if q else None
                for field,pattern in [('service_evidence',SERVICE),('independence_evidence',INDEPENDENT),('commercial_evidence',COMMERCIAL),('closed_evidence',CLOSED),('franchise_evidence',FRANCHISE)]:
                    p[field]=rendered_evidence(pattern) or p[field]
                for city in [p['city']]+[c for c in settings['territory'] if c!=p['city']]:
                    location=excerpt(re.sub(r'\s+',' ',rendered),address_pattern(city))
                    if city in settings['territory'] and location:
                        p['city']=city;p['territory_verified']=True;p['location_evidence']={'quote':location,'url':audit_url,'artifact':b['artifact'],'checked_at':b['checked_at']};break
                for value in re.findall(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)',rendered):
                    if not any(c['kind']=='phone' and phone_key(c['value'])==phone_key(value) for c in p['contacts']):
                        p['contacts'].append({'kind':'phone','value':value,'source':audit_url,'artifact':b['artifact']})
                for link in b.get('email_links',[]):
                    value=link['href'][7:].split('?')[0]
                    if re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value) and not any(c['kind']=='email' and c['value']==value for c in p['contacts']):
                        p['contacts'].append({'kind':'email','value':value,'source':audit_url,'artifact':b['artifact']})
                def finding(code,observation,impact,solution,points):
                    p['findings'].append({'code':code,'observation':observation,'impact':impact,'solution':solution,'points':points,'severity':'important','verified':True,'url':audit_url,'artifact':b['artifact'],'screenshot':b.get('screenshot'),'checked_at':b['checked_at']})
                if b['layout_width']>600 and b['small_text_count']>=5:
                    finding('mobile_scaled_text',f"At a 390px mobile screen the page uses a {b['layout_width']}px layout; {b['small_text_count']} text elements render below 10 effective pixels.",'Customers may need to zoom to read services and contact information.','Build a responsive service page with readable text and a clear phone/quote action.',25)
                elif b['document_width']>b['client_width']*1.15:
                    finding('mobile_overflow',f"Mobile content is {b['document_width']}px wide in a {b['client_width']}px viewport.",'Horizontal scrolling can make the service and contact path harder to use.','Correct the fixed-width layout and verify key services and contacts at phone widths.',20)
                accessibility=b.get('accessibility',{})
                if accessibility.get('status')=='completed':
                    violations={v['id']:v for v in accessibility['violations']}
                    labels=[n for n in violations.get('label',{}).get('nodes',[]) if n['in_form'] and not n['in_footer']]
                    if len(labels)>=2:
                        finding('unlabeled_form',f"axe-core confirmed {len(labels)} form fields without an accessible label.",'People using assistive technology may have difficulty identifying the fields needed to make an inquiry.','Give inquiry fields persistent accessible names and verify keyboard operation.',15)
                        p['findings'][-1].update(axe_rule='label',selectors=[n['target'] for n in labels],engine=accessibility['engine'])
                    contrast=[n for n in violations.get('color-contrast',{}).get('nodes',[]) if not n['in_footer'] and len(n['text'])>=8]
                    if len(contrast)>=3:
                        finding('low_text_contrast',f"axe-core confirmed insufficient foreground/background contrast on {len(contrast)} non-footer text elements.",'Some visitors may struggle to read service information and inquiry controls, especially with low vision.','Improve text/background contrast on the affected service and inquiry content, then verify it on a phone.',20)
                        p['findings'][-1].update(axe_rule='color-contrast',selectors=[n['target'] for n in contrast],engine=accessibility['engine'])
                else:
                    p['unverified'].append('Standard accessibility scan: '+accessibility.get('reason','unavailable'))
                if p['contacts'] and any(c['kind']=='phone' for c in p['contacts']) and not b['phone_links']:
                    # Supplementary 10 points only; by itself not a meaningful qualification finding.
                    p['findings'].append({'code':'phone_not_linked','observation':'The rendered home page has no tel: links; a public phone number is present in the audited pages.','impact':'Phone visitors must copy or dial the number manually.','solution':'Add a clear tap-to-call action.','points':10,'severity':'supporting','verified':True,'url':audit_url,'artifact':b['artifact'],'checked_at':b['checked_at']})
            else:p['unverified'].append('Mobile rendering: '+b.get('error','unknown'))
    else:p['unverified'].append('Mobile rendering unavailable or source fetch blocked')
    # A service-area mention is insufficient. Corroborate missing locality/ownership
    # with an indexed public listing only when its phone matches the official site.
    if (not p['territory_verified'] or not p['independence_evidence']) and any(c['kind']=='phone' for c in p['contacts']):
        from .search import search
        from bs4 import BeautifulSoup
        phone=next(c['value'] for c in p['contacts'] if c['kind']=='phone')
        research=search(p['name']+' '+phone+' business address owner',fetcher.root)
        key=hashlib.sha256((run_id+p['website']+'identity').encode()).hexdigest()[:20]
        artifact=fetcher.root/'data/evidence'/(key+'-identity-search.json')
        artifact.write_text(json.dumps(research,indent=2))
        for result in research['results']:
            text=BeautifulSoup(result['title']+' '+result['snippet'],'html.parser').get_text(' ',strip=True)
            if phone_key(phone) not in re.sub(r'\D','',text):continue
            def corroboration(quote):
                return {'quote':quote,'url':result['url'],'artifact':str(artifact.relative_to(fetcher.root)),'checked_at':research['checked_at'],'method':str(research['provider'])+' indexed public listing; phone matched to official website. Listing may be stale.'}
            if not p['territory_verified']:
                for city in settings['territory']:
                    quote=excerpt(text,address_pattern(city))
                    if quote:
                        p['city']=city;p['territory_verified']=True;p['location_evidence']=corroboration(quote);break
            if not p['independence_evidence']:
                quote=excerpt(text,INDEPENDENT)
                if quote:p['independence_evidence']=corroboration(quote)
    p['contacts']=[c for c in p['contacts'] if c['kind']!='email' or valid_email(c['value'])]
    for c in p['contacts']:
        if c['kind']=='email':c['value']=unquote(c['value']).lower()
    classify(p,' '.join([parsed['text'] for raw,parsed in texts]+[b.get('text','') for b in p.get('browser_checks',[]) if b.get('verified')]))
    if p.get('maps_closed'):
        p['closed_evidence']={'quote':'Maps listing displays permanently closed','url':p.get('maps_url',''),'checked_at':p.get('maps_checked_at','')}
    if p.get('maps_phone'):
        official={phone_key(c['value']) for c in p['contacts'] if c['kind']=='phone'}
        if phone_key(p['maps_phone']) in official and p.get('maps_address'):
            for city in settings['territory']:
                if re.search(address_pattern(city),p['maps_address'],re.I):
                    p.update(city=city,territory_verified=True,location_evidence={'quote':p['maps_address'],'url':p['maps_url'],'artifact':p.get('maps_artifact',''),'checked_at':p['maps_checked_at'],'method':'Maps address matched to official website phone'})
                    break
    p.update(email_fields(p))
    # Supporting issues count only when a meaningful issue is independently verified.
    score(p,settings)
    p['suggested_solution']=next((f['solution'] for f in p['findings'] if f['severity']=='important'),'Review unverified checks before proposing work.')
    p['outreach_angle']=outreach_angle(p)
    p['next_action']='Owner review the evidence and public contact, then approve a personal free-look approach.' if p['qualified'] else 'Resolve qualification gaps; do not pitch from this record yet.'
    return p


def make_draft(p):
    issue=next(f for f in p['findings'] if f['verified'] and f['severity']=='important')
    wording={'mobile_scaled_text':'your website shrinks a desktop-width layout onto a phone, making the service information small to read',
             'mobile_overflow':'part of your website extends beyond the phone screen and requires horizontal scrolling',
             'unlabeled_form':'several inquiry fields are missing accessible labels, which can make the form harder to use with assistive technology',
             'low_text_contrast':'some of your website text has low contrast against its background, making it harder to read'}[issue['code']]
    email=next((c['value'] for c in p['contacts'] if c['kind']=='email'),'')
    detail=''
    if issue['code']=='low_text_contrast':
        nodes=[n for b in p.get('browser_checks',[]) if b['url']==issue['url'] for v in b.get('accessibility',{}).get('violations',[]) if v['id']=='color-contrast' for n in v['nodes'] if not n['in_footer'] and len(n['text'])>=8]
        nodes.sort(key=lambda n:0 if re.search(r'@|\d{3}[- .]\d{3}|contact',n['text'],re.I) else 1 if re.search(r'repair|service|water|toilet|heat|cool|maintenance',n['text'],re.I) else 2)
        if nodes:detail=' For example, the “'+re.sub(r'\s+',' ',nodes[0]['text']).strip()[:90]+'” text came up in the readability check.'
    angle={'unlabeled_form':'a small improvement to make the inquiry form clearer to use','low_text_contrast':'a small set of changes to make the service and contact information easier to read'}.get(issue['code'],'a clearer, phone-friendly service and contact page')
    body=f"Hi {p['name']} team,\n\nI'm Donovin with Clockout in Roscoe. I took a look at your website and noticed {wording}.{detail}\n\nI help local businesses make it easier for customers to understand their services and get in touch. Would you be open to a free look at {angle}?\n\nDonovin\nClockout\nhttps://clockout.us\n"
    return {'prospect_id':p['id'],'to':email,'subject':f"A website idea for {p['name']}",'body':body,'contact_fallback':p['contacts'],'evidence_url':issue['url'],'evidence_checked_at':issue['checked_at'],'finding_code':issue['code'],'status':'owner review; unsent','note':'Email address unavailable: use the verified public contact to request the right recipient.' if not email else ''}


def safe_cell(v):
    s=str(v)
    return "'"+s if s.lstrip().startswith(('=','+','-','@')) or s.startswith(('\t','\r')) else s


def export(root,store,run_id,summary,review_signals=None):
    root=Path(root); folder=root/'data/runs'/run_id;folder.mkdir(parents=True,exist_ok=True)
    leads=store.all(); qualified=[p for p in leads if p['qualified']]
    fields=FIELDS
    with (root/'data/prospects.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for p in leads:
            row=dict(id=p['id'],name=p['name'],city=p['city'],industry=p['industry'],website=p['website'],public_contacts='; '.join(c['value'] for c in p['contacts']),contact_source='; '.join(dict.fromkeys(c['source'] for c in p['contacts'])),website_findings=readable_findings(p),evidence_urls='; '.join(dict.fromkeys([x['url'] for x in p['pages']]+[p[k]['url'] for k in ('location_evidence','independence_evidence','commercial_evidence') if p.get(k)])),verification_date=p['checked_at'],score=p['score']['total'],qualification_status='qualified' if p['qualified'] else 'needs review: '+'; '.join(p['qualification_reasons']),suggested_solution=p['suggested_solution'],outreach_angle=outreach_angle(p),outreach_status=p['outreach_status'],follow_up_date=p['follow_up_date'],next_action=p['next_action'],last_researched=p['checked_at'])
            row.update({k:p.get(k,'') if p.get(k) is not None else '' for k in FIELDS[18:]})
            row.update(email_fields(p))
            w.writerow({k:safe_cell(v) for k,v in row.items()})
    drafts=[]
    eligible=[p for p in qualified if p['outreach_status']=='not contacted']
    eligible.sort(key=lambda p:(not any(c['kind']=='email' for c in p['contacts']),-p['score']['total']))
    selected=eligible[:3];selected_ids={p['id'] for p in selected}
    current={p['id']:p for p in qualified}
    for old_path in (root/'data/drafts').glob('*.json'):
        old=json.loads(old_path.read_text());p=current.get(old['prospect_id'])
        codes={f['code'] for f in p['findings'] if f['verified'] and f['severity']=='important'} if p else set()
        if not p or old['prospect_id'] not in selected_ids or old.get('finding_code') not in codes:
            archive=root/'data/drafts/archive';archive.mkdir(parents=True,exist_ok=True)
            old_path.rename(archive/(run_id+'-'+old_path.name))
    for p in selected:
        draft=make_draft(p)
        path=root/'data/drafts'/f"{p['id']}.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_text(json.dumps(draft,indent=2))
        drafts.append(json.loads(path.read_text()))
    for p in eligible:
        if not any(c['kind']=='email' for c in p['contacts']):
            out=root/'data/outreach';out.mkdir(parents=True,exist_ok=True)
            phone=next((c['value'] for c in p['contacts'] if c['kind']=='phone'),'public phone in tracker')
            note=f"Owner-reviewed call outline for {p['name']} — {phone}\n\nAsk for the person responsible for the website. Introduce Donovin from Clockout in Roscoe.\nVerified observation: "+next(f['observation'] for f in p['findings'] if f['severity']=='important')+f"\nOffer a free look at one practical improvement. Ask permission to share a short note and request the appropriate business email.\nNo call placed. Budget, buying intent and decision-maker identity remain unknown.\nEvidence: {p['website']}\n"
            (out/(p['id']+'-call-outline.txt')).write_text(note)
    report=[f'# Opportunity Hunter — {run_id}', '',json.dumps(summary,indent=2),'', 'Qualification indicates a potential need, not verified buying intent. No outreach sent.','',f'{len(qualified)} qualified in local tracker; {len(leads)} total records.','']
    for p in leads:
        report += [f"## {p['name']} — {p['city']} — {p['score']['total']}/100",f"Status: {'qualified' if p['qualified'] else 'needs review'}; outreach: {p['outreach_status']}",f"Website: {p['website']}",f"Score: {json.dumps(p['score'])}",f"Contacts: {'; '.join(c['value'] for c in p['contacts'])}"]
        for f in p['findings']:report += [f"- {f['observation']} Evidence: {f['url']} ({f['artifact']}); checked {f['checked_at']}",f"  Why it may matter: {f['impact']}"]
        for k in ['location_evidence','independence_evidence','commercial_evidence']:
            if p.get(k):report += [f"{k}: {p[k]['quote']} — {p[k]['url']}"]
        report += [f"Solution: {p['suggested_solution']}",f"Next: {p['next_action']}",f"Gaps: {'; '.join(p['qualification_reasons']+p['unverified'])}",'']
    if review_signals is not None:
        # Optional, informational enrichment; scores and qualification above are already final.
        from . import review_signals as rs
        businesses,warnings=rs.load(review_signals)
        summary['review_signals']={'file':str(review_signals),'entries':len(businesses),'warnings':warnings}
        for w in warnings:print('Warning: '+w,flush=True)
        if businesses:
            report += rs.report_lines(leads,businesses)
            rows=rs.csv_rows(leads,businesses);summary['review_signals']['matched_prospects']=len(rows)
            with (root/'data/review-signals.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=rs.CSV_FIELDS);w.writeheader()
                for row in rows:w.writerow({k:safe_cell(v) for k,v in row.items()})
    (folder/'report.md').write_text('\n'.join(report));(root/'data/latest-report.md').write_text('\n'.join(report))
    (folder/'summary.json').write_text(json.dumps(summary,indent=2))
    return qualified,drafts
