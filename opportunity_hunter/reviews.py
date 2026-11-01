"""Manual, optional review research; review claims never become website audit facts."""
import difflib
import fcntl
import json
import os
import re
import signal
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit,unquote
from .web import now

PROFILE='opportunity-hunter'
# Only direct problem statements are surfaced. Each is still an unverified reviewer claim.
TOPICS={
 'phone_response':r"\b(?:no one|nobody) (?:answered|answers|picked up)|\b(?:never|didn't|did not|won't|wouldn't) (?:call(?:ed)? (?:me |us )?back|return(?:ed)? (?:my |our )?(?:calls?|messages?))\b",
 'booking':r"\b(?:couldn't|could not|unable to|impossible to|hard to|difficult to) (?:book|schedule|make an appointment)\b",
 'website':r"\b(?:website|web site|contact form)\b[^.!?]{0,60}\b(?:broken|not working|doesn't work|did not work|unusable)\b",
 'hours':r"\b(?:hours|opening times)\b[^.!?]{0,40}\b(?:wrong|incorrect|outdated|inaccurate)\b"}


def review_signals(reviews):
    signals=[]
    for r in reviews:
        text=r.get('reviewText') or ''
        if r.get('textTruncated'):continue
        for topic,pattern in TOPICS.items():
            match=re.search(pattern,text,re.I)
            if not match:continue
            sentence=re.split(r'(?<=[.!?])\s+',text)
            quote=next((s for s in sentence if re.search(pattern,s,re.I)),text)
            if re.search(r'\b(?:another|other|previous) (?:business|company|shop|contractor)\b',quote,re.I):continue
            if re.search(r'\b(?:not|never)\s+(?:broken|wrong|incorrect|outdated|inaccurate|unusable)\b',quote,re.I):continue
            signals.append({'topic':topic,'quote':quote[:650],'review_id':r.get('reviewId'),'review_url':r.get('reviewUrl'),
                            'published_date_raw':r.get('publishedDateRaw'),'rating':r.get('rating'),
                            'status':'Reviewer report — human corroboration required'})
    return signals


def normalized_name(value):
    return re.sub(r'[^a-z0-9]','',re.sub(r'\b(?:and|inc|llc|company|co)\b',' ',value.lower().replace('&',' ')))


def identity_matches(prospect, place):
    if not place.get('placeId') or not place.get('name'):return False
    expected=prospect.get('maps_cid')
    if expected and expected!=place['placeId']:return False
    a,b=normalized_name(prospect['name']),normalized_name(place['name'])
    return bool(a and b and (a in b or b in a or difflib.SequenceMatcher(None,a,b).ratio()>=0.72))


def terminate_group(proc):
    try:os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait()


def collect_one(root, prospect, limit=10, anonymous=False, timeout=90, visible=False, sort='newest', mode='collect'):
    root=Path(root).resolve()
    if not 1<=limit<=30:raise ValueError('Review limit must be 1–30 per business')
    if not 10<=timeout<=120:raise ValueError('Review timeout must be 10–120 seconds')
    url=prospect.get('maps_url','');parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('google.com','www.google.com') or not parsed.path.startswith(('/maps/place/','/maps/search/')) or parsed.username or parsed.password or parsed.port not in (None,443):
        return {'status':'unavailable','business':prospect['name'],'prospect_id':prospect['id'],'identity_verified':False,'reviews':[],'signals':[], 'termination':{'reason':'missing-maps-url'},'coverage':'unavailable','checked_at':now()}
    from .review_session import endpoint
    address=endpoint(root) if not anonymous else None
    if not anonymous and not address:
        return {'status':'needs_browser','business':prospect['name'],'prospect_id':prospect['id'],'identity_verified':False,'reviews':[],'signals':[], 'termination':{'reason':'dedicated-browser-not-open'},'coverage':'unavailable','checked_at':now()}
    folder=root/'data/reviews'/uuid.uuid4().hex;folder.mkdir(parents=True,mode=0o700)
    output=folder/'result.json';request=folder/'request.json'
    result={'status':'running','place':{},'reviews':[],'termination':{'reason':'running'},'auth_state':'unknown','checked_at':now()}
    output.write_text(json.dumps(result));output.chmod(0o600)
    request.write_text(json.dumps({'url':url,'limit':limit,'anonymous':anonymous,'timeout':timeout,'visible':visible,'sort':sort,'output':str(output),'endpoint':address,'mode':mode,'phone':prospect.get('maps_phone') or next((c['value'] for c in prospect.get('contacts',[]) if c['kind']=='phone'),'')}))
    env=dict(os.environ);tmp=root/'data/tmp';tmp.mkdir(exist_ok=True);env['TMPDIR']=str(tmp);env['NO_PROXY']=','.join(filter(None,[env.get('NO_PROXY',''),'127.0.0.1','localhost','::1']))
    started=time.monotonic();timed_out=False
    try:
        with (folder/'collector.log').open('w') as log:
            proc=subprocess.Popen(['node',str(root/'opportunity_hunter/review_bridge.mjs'),str(request)],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
            try:proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;terminate_group(proc)
            finally:
                # Persistent Chrome must be closed before the next manual run.
                terminate_group(proc)
        result=json.loads(output.read_text())
        if timed_out:result.update(status='incomplete',termination={'reason':'deadline','authState':result.get('auth_state','unknown')})
        elif result['status']=='running':result.update(status='unavailable',termination={'reason':'collector-runtime-unavailable'})
    except OSError as error:result.update(status='unavailable',termination={'reason':'collector-runtime-unavailable','error_type':type(error).__name__})
    matched=identity_matches(prospect,result.get('place',{})) and result.get('identity_phone_verified',False)
    if result.get('place',{}).get('name') and not matched:
        result['status']='identity_review';result['termination']['reason']='place-mismatch'
    result.update(prospect_id=prospect['id'],business=prospect['name'],identity_verified=matched,
                  artifact=str(output.relative_to(root)),elapsed_seconds=round(time.monotonic()-started,2),requested_limit=limit,
                  signals=review_signals(result.get('reviews',[])) if matched else [])
    reason=result['termination'].get('reason')
    result['coverage']='sample; not a complete review history' if reason=='limit-reached' else 'end observed' if reason in ('no-more-reviews','no-reviews') else 'incomplete or unavailable'
    result['note']='Review statements are unverified reports; absence of keyword matches does not establish absence of problems.'
    output.write_text(json.dumps(result,indent=2));return result


def attach_research(store, prospect, result):
    """Update only supplemental JSON; preserve score, qualification and all human fields."""
    if not result.get('identity_verified'):
        # Keep any earlier matched collection; record the latest failed attempt separately.
        field='review_last_attempt'
    else:field='review_research'
    row=store.db.execute('SELECT payload FROM prospects WHERE id=?',(prospect['id'],)).fetchone()
    if not row:raise ValueError('Unknown prospect ID')
    payload=json.loads(row[0]);payload[field]={k:v for k,v in result.items() if k!='reviews'}
    if result.get('identity_verified'):
        prior=payload.get('review_records',[]);records={r['reviewId']:r for r in prior if r.get('reviewId')}
        for r in result.get('reviews',[]):
            if r.get('reviewId'):records[r['reviewId']]=r
        payload['review_records']=list(records.values())
    with store.db:store.db.execute('UPDATE prospects SET payload=? WHERE id=?',(json.dumps(payload),prospect['id']))


def write_report(root, results):
    root=Path(root);lines=['# Review research','', 'Manual collection only. Review statements require corroboration; website qualification and outreach remain unchanged.','']
    for r in results:
        lines += [f"## {r['business']}",f"Status: {r['status']}; auth: {r.get('auth_state','unknown')}; termination: {r.get('termination',{}).get('reason')}",
                  f"Collected: {len(r.get('reviews',[]))}; collector-reported total (unverified): {r.get('place',{}).get('reviewsCount')}; coverage: {r.get('coverage','unknown')}",
                  f"Evidence: {r.get('artifact','unavailable')}"]
        lines += [f"- {s['topic']}: {s['quote']} ({s.get('review_url') or 'review URL unavailable'}); {s['status']}" for s in r.get('signals',[])]
        lines += [('No keyword matches in the collected sample; this does not establish absence of problems.' if r.get('identity_verified') and r.get('reviews') else 'Review evidence unavailable or identity unconfirmed; no conclusion.') if not r.get('signals') else '', '']
    out=root/'data/reviews/latest-report.md';out.parent.mkdir(exist_ok=True);out.write_text('\n'.join(lines));return out


def run_reviews(root, store, ids=None, qualified=False, limit=10, anonymous=False, timeout=90, visible=False):
    root=Path(root)
    with (root/'data/reviews.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another review run is active')
        prospects=store.all()
        if ids:
            unknown=set(ids)-{p['id'] for p in prospects}
            if unknown:raise ValueError('Unknown prospect ID')
            prospects=[p for p in prospects if p['id'] in ids]
        elif qualified:prospects=[p for p in prospects if p['qualified']]
        else:raise ValueError('Select --qualified or --prospect ID')
        results=[]
        for p in prospects[:5]:
            r=collect_one(root,p,limit,anonymous,timeout,visible);attach_research(store,p,r);results.append(r)
            print(json.dumps({'business':p['name'],'status':r['status'],'reviews':len(r.get('reviews',[])),'reason':r.get('termination',{}).get('reason'),'elapsed_seconds':r.get('elapsed_seconds')}),flush=True)
            write_report(root,results)
        return results
