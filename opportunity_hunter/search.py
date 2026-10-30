"""Tavily default, Brave fallback; missing keys never block seeded public research."""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from .web import now

_last_request=0


def load_keys(root):
    env=dict(os.environ)
    file=Path(root)/'.env'
    if file.exists():
        for line in file.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1);env.setdefault(k.strip(),v.strip().strip('\"\''))
    return env


def search(query,root):
    global _last_request
    env=load_keys(root);errors=[]
    providers=[('tavily',env.get('TAVILY_API_KEY')),('brave',env.get('BRAVE_API_KEY') or env.get('BRAVE_SEARCH_API_KEY'))]
    for name,key in providers:
        if not key:errors.append(name+': key unconfigured');continue
        try:
            time.sleep(max(0,1.1-(time.monotonic()-_last_request)))
            _last_request=time.monotonic()
            if name=='tavily':
                req=urllib.request.Request('https://api.tavily.com/search',data=json.dumps({'query':query,'search_depth':'basic','max_results':10,'include_answer':False,'include_raw_content':False}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            else:
                req=urllib.request.Request('https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':query,'count':10,'country':'US','search_lang':'en'}),headers={'X-Subscription-Token':key,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=20) as r:body=json.load(r)
            results=body.get('results',[]) if name=='tavily' else body.get('web',{}).get('results',[])
            if not results:errors.append(name+': no results');continue
            clean=[{'title':r.get('title',''),'url':r.get('url',''),'snippet':r.get('content',r.get('description',''))} for r in results if r.get('url','').startswith(('http://','https://'))]
            return {'provider':name,'query':query,'checked_at':now(),'results':clean,'fallback_errors':errors}
        except Exception as e:
            errors.append(name+': '+type(e).__name__+'; check key, balance or provider availability')
    return {'provider':None,'query':query,'checked_at':now(),'results':[],'errors':errors}
