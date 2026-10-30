"""Optional explicit sync. No email send endpoint exists in this project."""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from .engine import Store
from .web import now


def request_json(url, payload=None, token=None, method=None):
    data=json.dumps(payload).encode() if payload is not None else None
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        # Never include request URLs (Telegram embeds its token) or response bodies in errors/logs.
        raise RuntimeError(f'Integration HTTP {e.code}; check authorization and configured resource') from None
    except Exception as e:
        raise RuntimeError('Integration transport failed: '+type(e).__name__) from None


def sync_gmail(root,store,token):
    if not token:return {'status':'unconfigured','reason':'Set OPPORTUNITY_GOOGLE_ACCESS_TOKEN for standalone Gmail drafts, or use the connected Codex Gmail plugin.'}
    done=[]
    for path in sorted((Path(root)/'data/drafts').glob('*.json')):
        draft=json.loads(path.read_text());pid=draft['prospect_id']
        existing=store.db.execute('SELECT remote_id FROM integration_receipts WHERE kind=? AND local_id=?',('gmail',pid)).fetchone()
        if existing:done.append(existing[0]);continue
        row=store.db.execute('SELECT payload,outreach_status FROM prospects WHERE id=?',(pid,)).fetchone()
        if not row or not json.loads(row[0])['qualified'] or row[1]!='not contacted' or not draft['to']:continue
        # A previous ambiguous create is never automatically retried; reconcile Gmail manually first.
        claim=store.db.execute('SELECT remote_id FROM integration_receipts WHERE kind=? AND local_id=?',('gmail_pending',pid)).fetchone()
        if claim:continue
        store.db.execute('INSERT INTO integration_receipts VALUES(?,?,?)',('gmail_pending',pid,now()));store.db.commit()
        msg=EmailMessage();msg['To']=draft['to'];msg['Subject']=draft['subject'];msg.set_content(draft['body'])
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result=request_json('https://gmail.googleapis.com/gmail/v1/users/me/drafts',{'message':{'raw':raw}},token)
        if not result.get('id'):raise RuntimeError('Gmail returned no draft ID; creation unconfirmed')
        with store.db:
            store.db.execute('INSERT INTO integration_receipts VALUES(?,?,?)',('gmail',pid,result['id']))
            store.db.execute('DELETE FROM integration_receipts WHERE kind=? AND local_id=?',('gmail_pending',pid))
        done.append(result['id'])
    return {'status':'working','draft_ids':done,'sent':0}


def sync_sheets(root,store,token,sheet_id):
    import csv
    if not token or not sheet_id:return {'status':'unconfigured','reason':'Configure google_sheet_id in config/local.json and OPPORTUNITY_GOOGLE_ACCESS_TOKEN, or use the connected Codex Sheets plugin.'}
    base='https://sheets.googleapis.com/v4/spreadsheets/'+urllib.parse.quote(sheet_id,safe='')
    metadata=request_json(base+'?fields=sheets(properties(title,gridProperties(rowCount,columnCount)))',token=token)
    props=next((x.get('properties',{}) for x in metadata.get('sheets',[]) if x.get('properties',{}).get('title')=='OpportunityHunter'),None)
    if not props: raise RuntimeError('OpportunityHunter sheet tab not found')
    grid=props.get('gridProperties',{})
    grid_cols=int(grid.get('columnCount',26))
    if grid_cols<1 or grid_cols>50000:raise RuntimeError('Unsupported sheet grid width')
    grid_rows=min(int(grid.get('rowCount',1000)),1000,50000//grid_cols)
    response=request_json(base+'/values/'+urllib.parse.quote(f'OpportunityHunter!A1:{_col(grid_cols)}{grid_rows}',safe=''),token=token)
    rows=response.get('values',[])
    with (Path(root)/'data/prospects.csv').open(newline='') as f:
        reader=csv.DictReader(f);header=reader.fieldnames;local=list(reader)
    base_fields=['id','name','city','industry','website','public_contacts','contact_source','website_findings','evidence_urls','verification_date','score','qualification_status','suggested_solution','outreach_angle','outreach_status','follow_up_date','next_action','last_researched']
    maps_fields=['maps_url','google_category','google_rating','google_review_count','maps_checked_at','public_emails','email_sources','email_verification_status']
    if any(x not in header for x in base_fields): raise RuntimeError('Local CRM header is missing required fields')
    if not header:raise RuntimeError('Local CRM has no header')
    local_ids=[p.get('id') for p in local]
    if not all(local_ids) or len(set(local_ids))!=len(local_ids):raise RuntimeError('Local CRM contains missing or duplicate IDs')
    required=list(header)
    for field in maps_fields:
        if field not in required: required.append(field)
    if len(required)>grid_cols:
        raise RuntimeError(f'Sheet grid has {grid_cols} columns but CRM requires {len(required)}; expand the tab before sync')
    if len(set(required)) != len(required): raise RuntimeError('Local CRM header contains duplicates')
    if rows:
        cloud_header=rows[0]
        duplicates={h for h in cloud_header if h and cloud_header.count(h)>1}
        if duplicates: raise RuntimeError('Cloud CRM header contains duplicate columns: '+', '.join(sorted(duplicates)))
        # Existing headers may contain extra user columns and may be reordered. Add only
        # missing research columns at the end; never replace or reorder user columns.
        missing_base=[h for h in base_fields if h not in cloud_header]
        if missing_base: raise RuntimeError('Cloud CRM header is missing required fields: '+', '.join(missing_base))
        missing=[h for h in maps_fields if h not in cloud_header]
        if missing:
            old_len=max([len(cloud_header)]+[len(r) for r in rows[1:]])
            cloud_header=(cloud_header+['']*(old_len-len(cloud_header)))+missing
            if len(cloud_header)>grid_cols: raise RuntimeError('Sheet grid is too narrow for CRM columns')
            rows[0]=cloud_header
            updates_header={'range':f'OpportunityHunter!{_col(old_len+1)}1:{_col(len(cloud_header))}1','values':[missing]}
        else: updates_header=None
    else:
        cloud_header=required
        updates_header={'range':f'OpportunityHunter!A1:{_col(len(cloud_header))}1','values':[cloud_header]}
    if len(cloud_header)>grid_cols:raise RuntimeError('Cloud header exceeds sheet grid')
    index={h:i for i,h in enumerate(cloud_header)}
    # These are owned by the human CRM operator and are never written by research sync.
    owner_fields={'outreach_status','follow_up_date'}
    write_fields=[h for h in required if h in index and h not in owner_fields]
    if len(rows)>=grid_rows:raise RuntimeError('CRM read bound reached; expand and reconcile before sync')
    id_col=index.get('id')
    if id_col is None: raise RuntimeError('Cloud CRM is missing required id column')
    ids=[r[id_col] for r in rows[1:] if len(r)>id_col and r[id_col]]
    if len(set(ids)) != len(ids):raise RuntimeError('Duplicate IDs in cloud CRM; reconcile first')
    by_id={value:i+1 for i,value in enumerate([r[id_col] if len(r)>id_col else '' for r in rows[1:]],1) if value}
    updates=[]
    if updates_header: updates.append(updates_header)
    next_row=max(2,len(rows)+1)
    for p in local:
        if p['qualification_status']!='qualified':continue
        row=by_id.get(p['id'])
        if row is None:
            row=next_row;next_row+=1
            if row>grid_rows:raise RuntimeError('CRM row bound reached; expand and reconcile before sync')
            for field in owner_fields:
                updates.append({'range':f'OpportunityHunter!{_col(index[field]+1)}{row}','values':[[p.get(field,'')]]})
        for field in write_fields:
            if field not in p and field not in header: continue
            value=p.get(field,'')
            if field in ('maps_rating','google_rating'): field='google_rating'
            col=index.get(field)
            if col is None: continue
            updates.append({'range':f'OpportunityHunter!{_col(col+1)}{row}', 'values':[[_safe_sheet_cell(value)]]})
    if updates:
        result=request_json(base+'/values:batchUpdate',{'valueInputOption':'RAW','data':updates},token)
        expected=sum(len(row) for u in updates for row in u['values'])
        if result.get('totalUpdatedCells')!=expected:
            raise RuntimeError('Sheets update incomplete; reconcile before retry')
    return {'status':'working','url':'https://docs.google.com/spreadsheets/d/'+sheet_id,'ranges_written':len(updates)}


def _col(number):
    """Convert a one-based column number to A1 letters."""
    out=''
    while number:
        number, rem=divmod(number-1,26)
        out=chr(65+rem)+out
    return out


def _safe_sheet_cell(value):
    s=str(value)
    return "'"+s if s.lstrip().startswith(('=','+','-','@')) or s.startswith(('\t','\r')) else s


def telegram(root,store,run_id,env_file=None):
    env=dict(os.environ)
    if env_file:
        # Read the existing Hermes configuration without changing it or copying credentials.
        for line in Path(env_file).read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1)
                if k.strip() in ('TELEGRAM_BOT_TOKEN','TELEGRAM_HOME_CHANNEL'):
                    env[k.strip()]=v.strip().strip('\"\'')
    token=env.get('TELEGRAM_BOT_TOKEN');chat=env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:return {'status':'unconfigured','reason':'Existing Telegram bot token and owner home channel are required; CLI report remains available.'}
    existing=store.db.execute('SELECT remote_id FROM integration_receipts WHERE kind=? AND local_id=?',('telegram',run_id)).fetchone()
    if existing:return {'status':'already delivered','message_id':existing[0]}
    row=store.db.execute('SELECT summary,status FROM runs WHERE id=?',(run_id,)).fetchone()
    if not row or row[1] not in ('completed','partial'):raise RuntimeError('Only completed/partial research runs can notify')
    summary=json.loads(row[0]);top=[p for p in store.all() if p['qualified']][:3]
    text=f"Opportunity Hunter: {summary['researched']} researched, {summary['qualified_this_run']} qualified this run. No outreach sent.\n"
    text+='\n'.join(f"{p['name']}: {p['score']['total']}/100 — "+next(f['observation'] for f in p['findings'] if f['severity']=='important') for p in top)
    text+='\nNext: review data/latest-report.md and approve personal outreach.\nIntegrations: '+json.dumps(summary.get('integrations',{}))
    # Reserve delivery before sending: an ambiguous network failure needs manual reconciliation, never an automatic resend.
    pending=store.db.execute('SELECT 1 FROM integration_receipts WHERE kind=? AND local_id=?',('telegram_pending',run_id)).fetchone()
    if pending:return {'status':'needs reconciliation','reason':'Previous delivery unconfirmed; automatic resend prevented.'}
    store.db.execute('INSERT INTO integration_receipts VALUES(?,?,?)',('telegram_pending',run_id,now()));store.db.commit()
    result=request_json('https://api.telegram.org/bot'+token+'/sendMessage',{'chat_id':chat,'text':text[:3900],'disable_web_page_preview':True})
    if not result.get('ok') or not result.get('result',{}).get('message_id'):raise RuntimeError('Telegram delivery not confirmed')
    mid=str(result['result']['message_id'])
    with store.db:
        store.db.execute('INSERT INTO integration_receipts VALUES(?,?,?)',('telegram',run_id,mid))
        store.db.execute('DELETE FROM integration_receipts WHERE kind=? AND local_id=?',('telegram_pending',run_id))
    return {'status':'working','message_id':mid}
