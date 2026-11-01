"""Small backup parser adapted from google-maps-scraper-kit entity field paths.
Copyright (c) 2026 Mahan (github.com/Mahanaicoach); MIT, see third-party notices.
No CDP engine, server, installer or updater is imported.
"""
import json
import math
import re

FIELDS={'name':(11,),'maps_address':(18,),'website':(7,0),'maps_phone':(178,0,0),'google_category':(13,0),
        'google_rating':(4,7),'google_review_count':(4,8),'maps_place_id':(78,),'maps_cid':(10,)}


def dig(node, path):
    for index in path:
        if not isinstance(node,list) or index>=len(node):return None
        node=node[index]
    return node


def parse_entities(body):
    if len(body)>3_000_000:return []
    if body.startswith(")]}'"):body=body.split('\n',1)[-1]
    try:data=json.loads(body)
    except (ValueError,TypeError):return []
    todo=[data];out=[];seen=set();visited=0
    while todo and visited<10000:
        node=todo.pop();visited+=1
        if not isinstance(node,list):continue
        name=dig(node,(11,));place=dig(node,(78,));cid=dig(node,(10,))
        if isinstance(name,str) and name and (isinstance(place,str) and place.startswith('ChIJ') or isinstance(cid,str) and re.fullmatch(r'0x[0-9a-f]+:0x[0-9a-f]+',cid,re.I)):
            row={key:dig(node,path) for key,path in FIELDS.items()}
            rating=row['google_rating'];count=row['google_review_count']
            if isinstance(rating,bool) or not isinstance(rating,(int,float)) or not math.isfinite(rating) or not 0<=rating<=5:row['google_rating']=None
            if isinstance(count,bool) or not isinstance(count,int) or count<0:row['google_review_count']=None
            if not isinstance(row['website'],str) or not row['website'].startswith(('http://','https://')):row['website']=''
            identity=place or cid
            if identity not in seen:seen.add(identity);out.append(row)
        todo.extend(x for x in node if isinstance(x,list))
    return out


def merge_network(candidate, rows):
    """Fill missing fields only after matching a stable ID or public name+phone."""
    for row in rows:
        if any(candidate.get(k) and row.get(k) and candidate[k]!=row[k] for k in ('maps_place_id','maps_cid')):continue
        same_id=any(candidate.get(k) and candidate[k]==row.get(k) for k in ('maps_place_id','maps_cid'))
        phone=lambda v:re.sub(r'\D','',str(v or ''))[-10:]
        normal=lambda v:re.sub(r'[^a-z0-9]','',str(v or '').lower())
        same_identity=(normal(candidate['name'])==normal(row['name']) and len(phone(candidate.get('maps_phone')))==10 and phone(candidate['maps_phone'])==phone(row.get('maps_phone')))
        if not (same_id or same_identity):continue
        for k,v in row.items():
            if k!='name' and candidate.get(k) in (None,'') and v not in (None,''):
                candidate[k]=v;candidate.setdefault('maps_network_fields',[]).append(k)
        return candidate
    return candidate
