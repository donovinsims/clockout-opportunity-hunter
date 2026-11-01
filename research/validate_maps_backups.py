"""Bounded manual comparison of the integrated Maps paths on existing prospects."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from opportunity_hunter.engine import Store,phone_key
from opportunity_hunter.maps import discover_maps

store=Store(ROOT);prospects=[p for p in store.all() if p['qualified']]
folder=ROOT/'data/kit-comparison';folder.mkdir(parents=True,exist_ok=True)
protected=lambda p:{k:p.get(k) for k in ('name','city','industry','findings','suggested_solution','score','qualified','qualification_reasons','outreach_status','follow_up_date')}
before={p['id']:protected(p) for p in prospects}
(folder/'pre-refresh-state.json').write_text(json.dumps(before,indent=2))
results=[]
for p in prospects[:5]:
 result=discover_maps(ROOT,p['name'],p['city'],1)
 matched=None
 for candidate in result['candidates']:
  phones={phone_key(c['value']) for c in p.get('contacts',[]) if c['kind']=='phone'}
  if phone_key(candidate.get('maps_phone','')) not in phones:continue
  if p.get('maps_cid') and candidate.get('maps_cid') and p['maps_cid']!=candidate['maps_cid']:continue
  matched=candidate;break
 if matched:
  with store.db:
   row=store.db.execute('SELECT payload FROM prospects WHERE id=?',(p['id'],)).fetchone()
   payload=json.loads(row[0]);payload.update({k:v for k,v in matched.items() if k.startswith(('maps_','google_'))})
   store.db.execute('UPDATE prospects SET payload=? WHERE id=?',(json.dumps(payload),p['id']))
 record={'prospect_id':p['id'],'name':p['name'],'matched':bool(matched),'rating':matched.get('google_rating') if matched else None,'review_count':matched.get('google_review_count') if matched else None,'network_fields':matched.get('maps_network_fields',[]) if matched else [],'elapsed_seconds':result['elapsed_seconds'],'artifact':result['artifact'],'errors':result['errors']}
 results.append(record);print(json.dumps(record),flush=True)
 (folder/'integrated-live.json').write_text(json.dumps(results,indent=2))
after={p['id']:protected(p) for p in store.all() if p['qualified']}
assert before==after,'Protected CRM fields changed'
store.db.close()
print('Protected CRM fields preserved; only supplemental Maps metadata refreshed.',flush=True)
