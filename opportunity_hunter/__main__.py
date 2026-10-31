import argparse
import fcntl
import json
import logging
import sys
import uuid
from pathlib import Path
from .web import Fetcher, parse_page, domain, now,directory_url
from .browser import Browser
from .engine import Store, audit, export, normal

ROOT=Path(__file__).resolve().parent.parent


def settings():
    s=json.loads((ROOT/'config/settings.json').read_text())
    local=ROOT/'config/local.json'
    if local.exists():s.update(json.loads(local.read_text()))
    return s


def discover(urls, city, limit, fetcher):
    """Discover from public directory links, then validate official sources in run.
    A directory may link member detail pages; follow up to 30 details once.
    No guessing business URLs or treating directory snippets as verified findings.
    """
    from bs4 import BeautifulSoup
    import re
    candidates=[];seen=set();details=[]
    excluded={'facebook.com','instagram.com','youtube.com','linkedin.com','twitter.com','x.com','google.com','yelp.com','chambermaster.com','growthzone.com'}
    def inspect(url, detail=False):
        page=fetcher.fetch(url)
        if page.get('error'):
            logging.warning(json.dumps({'event':'discovery_blocked','url':url,'error':page['error']}));return
        for a in BeautifulSoup(page['html'],'html.parser').select('a[href]'):
            from urllib.parse import urljoin
            dest=urljoin(page['url'],a['href']);host=domain(dest);label=a.get_text(' ',strip=True)
            if not host or not dest.startswith(('https://','http://')):continue
            if host==domain(url):
                if not detail and re.search(r'/member/|/members/|/details/|/list/member/',dest):details.append(dest)
                continue
            if host in excluded or any(host.endswith('.'+h) for h in excluded) or host in seen:continue
            if re.search(r'privacy|terms|login|powered|chambermaster|growthzone|wordpress',label+' '+host,re.I):continue
            if len(label)<3:continue
            # Directory labels can be Website/Visit Website. Resolve actual name from the destination title later.
            if len(candidates)>=limit:return
            seen.add(host)
            candidates.append({'name':label,'city':city,'industry':'service business (verify)','website':dest,'discovery_source':url})
    for u in urls:inspect(u)
    for u in list(dict.fromkeys(details))[:limit]:
        if len(candidates)>=limit:break
        inspect(u,True)
    return candidates


def run(args):
    s=settings();lock=(ROOT/'data/run.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another research run is active; overlap prevented.')
    store=Store(ROOT);rid=now().replace(':','').replace('+','_')+'-'+uuid.uuid4().hex[:5]
    # Holding the OS lock proves no earlier process still owns these incomplete runs.
    store.db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'",(now(),))
    store.db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(rid,'running',now(),None,None));store.db.commit()
    fetcher=Fetcher(ROOT,s);browser=None
    summary={'run_id':rid,'researched':0,'qualified_this_run':0,'created':0,'updated_existing':0,'failed':0,'outreach_sent':0,'integrations':{'sheets':'not synced; local CSV available','gmail':'local drafts; cloud sync separate','telegram':'disabled until explicitly configured; CLI report available'}}
    try:
        print('Starting manual research cycle '+rid,flush=True)
        browser=Browser(ROOT) if not args.no_browser else None
        if not args.candidates and not args.directory and not args.query:
            from .search import load_keys
            keys=load_keys(ROOT)
            if any(keys.get(k) for k in ('TAVILY_API_KEY','BRAVE_API_KEY','BRAVE_SEARCH_API_KEY')):
                region=args.city+(' WI' if args.city=='Beloit' else ' IL')
                args.query=[region+' family owned electrical contractors',region+' independent tree service',region+' family owned plumbing']
        candidate_file=args.candidates or (str(ROOT/'data/candidates.json') if not args.directory and not args.query and (ROOT/'data/candidates.json').exists() else None)
        candidates=json.loads(Path(candidate_file).read_text()) if candidate_file else []
        if args.query:
            from .search import search
            for query in args.query[:3]:
                result=search(query,ROOT)
                folder=ROOT/'data/runs'/rid;folder.mkdir(parents=True,exist_ok=True)
                (folder/('search-'+uuid.uuid4().hex[:8]+'.json')).write_text(json.dumps(result,indent=2))
                for item in result['results']:
                    if directory_url(item['url']):continue
                    existing=next((p for p in store.all() if domain(p['website'])==domain(item['url'])),None)
                    name=existing['name'] if existing else item['title'].split(' | ')[0]
                    candidates.append({'name':name,'city':existing['city'] if existing else args.city,'industry':'service business (verify)','website':item['url'],'discovery_source':f"{result['provider']} query: {query}"})
                if not result['results']:summary['integrations']['search']='Unavailable: '+'; '.join(result.get('errors',[]))
        if args.directory:
            candidates+=discover(args.directory,args.city,s['candidate_limit'],fetcher)
        if not candidates and (ROOT/'data/candidates.json').exists():
            candidates=json.loads((ROOT/'data/candidates.json').read_text())
            summary['discovery_fallback']='Re-auditing saved public candidates; no new discovery claimed.'
        if not candidates:raise ValueError('No candidates found. Supply a public directory URL or a researched candidate JSON file; blocked discovery never generates invented leads.')
        unique={}
        for c in candidates:
            for key in ('name','city','website'):
                if not c.get(key) and not (key=='website' and c.get('maps_url')):raise ValueError(f'Candidate missing {key}')
            unique.setdefault(domain(c['website']) or normal(c['name']+c['city']),c)
        for c in list(unique.values())[:min(args.limit,s['candidate_limit'])]:
            try:
                print('Auditing '+c['name'],flush=True)
                p=audit(c,fetcher,browser,s,rid)
                folder=ROOT/'data/runs'/rid;folder.mkdir(parents=True,exist_ok=True)
                (folder/(normal(c['name'])[:80]+'-audit.json')).write_text(json.dumps(p,indent=2))
                if p['qualified'] and summary['qualified_this_run']>=s['qualified_limit']:
                    p['qualified']=False;p['qualification_reasons'].append('Qualified batch cap reached; review next run')
                pid,status=store.upsert(p)
                summary['researched']+=1
                summary['qualified_this_run']+=int(p['qualified'])
                summary['created' if status=='created' else 'updated_existing']+=int(pid is not None)
                if not pid:summary['failed']+=1
                logging.info(json.dumps({'event':'candidate_complete','name':c['name'],'qualified':p['qualified'],'score':p['score']['total'],'persistence':status}))
                print(f"{c['name']}: {p['score']['total']}/100 — {'QUALIFIED' if p['qualified'] else '; '.join(p['qualification_reasons'])}",flush=True)
            except Exception as e:
                summary['failed']+=1
                logging.error(json.dumps({'event':'candidate_failed','name':c['name'],'type':type(e).__name__,'error':str(e)[:200]}))
        qualified,drafts=export(ROOT,store,rid,summary,getattr(args,'review_signals',None))
        summary['qualified_in_tracker']=len(qualified)
        summary['drafts_prepared']=len(drafts)
        state='completed' if not summary['failed'] else 'partial'
        store.db.execute('UPDATE runs SET status=?,finished_at=?,summary=? WHERE id=?',(state,now(),json.dumps(summary),rid));store.db.commit()
        # Save final counts after exports too.
        (ROOT/'data/runs'/rid/'summary.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary,indent=2));print('Tracker:',ROOT/'data/prospects.csv');print('Report:',ROOT/'data/latest-report.md')
    except BaseException as e:
        store.db.execute('UPDATE runs SET status=?,finished_at=?,summary=? WHERE id=?',('failed',now(),json.dumps({'error':type(e).__name__}),rid));store.db.commit()
        raise
    finally:
        if browser:browser.close()
        store.db.close();lock.close()


def main():
    for d in ('data','data/evidence','data/runs','data/drafts','logs'):(ROOT/d).mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=ROOT/'logs/hunter.jsonl',level=logging.INFO,format='%(message)s')
    parser=argparse.ArgumentParser(description='Opportunity Hunter — manual research, evidence and unsent drafts')
    sub=parser.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--candidates');r.add_argument('--directory',action='append');r.add_argument('--query',action='append');r.add_argument('--city',default='Rockford');r.add_argument('--limit',type=int,default=30);r.add_argument('--no-browser',action='store_true');r.add_argument('--review-signals',help='optional gmr signals.json; informational, never scored')
    d=sub.add_parser('discover');d.add_argument('--directory',action='append');d.add_argument('--maps',action='store_true');d.add_argument('--query');d.add_argument('--city',required=True);d.add_argument('--output',default='data/discovered.json');d.add_argument('--limit',type=int,default=30)
    sub.add_parser('status')
    sy=sub.add_parser('sync');sy.add_argument('--gmail',action='store_true');sy.add_argument('--sheets',action='store_true');sy.add_argument('--telegram-run');sy.add_argument('--hermes-env')
    e=sub.add_parser('export');e.add_argument('--review-signals',help='optional gmr signals.json; informational, never scored')
    m=sub.add_parser('mark');m.add_argument('id');m.add_argument('--status',required=True,choices=['not contacted','draft prepared','contacted','replied','do not contact','won','lost']);m.add_argument('--follow-up',default='')
    args=parser.parse_args()
    if args.command=='run':run(args)
    elif args.command=='discover':
        out=Path(args.output).resolve()
        if not out.is_relative_to(ROOT):parser.error('Output must remain inside this project')
        if args.city not in settings()['territory']:parser.error('City must be one of the eight approved towns')
        if args.maps:
            if not args.query or args.directory:parser.error('--maps requires --query and cannot combine with --directory')
            from .maps import discover_maps
            result=discover_maps(ROOT,args.query,args.city,args.limit);rows=result['candidates']
            print(json.dumps({k:v for k,v in result.items() if k!='candidates'},indent=2))
        else:
            if not args.directory:parser.error('Supply --directory or --maps --query')
            rows=discover(args.directory,args.city,min(args.limit,30),Fetcher(ROOT,settings()))
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(rows,indent=2));print(f'{len(rows)} discovered candidates saved to {out}; not qualified until audited.')
    else:
        store=Store(ROOT)
        if args.command=='sync':
            from .integrations import sync_gmail,sync_sheets,telegram
            from .search import load_keys
            token=load_keys(ROOT).get('OPPORTUNITY_GOOGLE_ACCESS_TOKEN');result={}
            for kind,enabled,action in [('gmail',args.gmail,lambda:sync_gmail(ROOT,store,token)),('sheets',args.sheets,lambda:sync_sheets(ROOT,store,token,settings().get('google_sheet_id'))),('telegram',args.telegram_run,lambda:telegram(ROOT,store,args.telegram_run,args.hermes_env))]:
                if enabled:
                    try:result[kind]=action()
                    except Exception as e:result[kind]={'status':'failed','reason':str(e)}
            print(json.dumps(result or {'status':'No integration selected; core unchanged.'},indent=2))
            (ROOT/'data/integration-status.json').write_text(json.dumps(result,indent=2))
        elif args.command=='status':
            print(json.dumps({'total':len(store.all()),'qualified':sum(p['qualified'] for p in store.all()),'latest_runs':store.db.execute('SELECT id,status,summary FROM runs ORDER BY started_at DESC LIMIT 3').fetchall(),'scheduled':False,'remote_git':'none; never pushed'},indent=2))
        elif args.command=='mark':
            with store.db:
                cur=store.db.execute('UPDATE prospects SET outreach_status=?,follow_up_date=? WHERE id=?',(args.status,args.follow_up,args.id))
            if not cur.rowcount:parser.error('Unknown prospect ID')
            print('Human sales status saved; research reruns preserve it.')
        else:export(ROOT,store,'export-'+now().replace(':',''),{'manual_export':True},args.review_signals)
        store.db.close()

if __name__=='__main__':main()
