import express from 'express';
import path from 'node:path';
import { PROJECT_ROOT, DEFAULT_DB } from '../core/paths.js';
import { createStore } from '../core/store.js';
import { positiveNumber } from '../core/config.js';
import { redact } from '../core/redact.js';
import { toCsv, toJsonExport } from '../export/exporters.js';

export function createDashboardServer({dbPath=DEFAULT_DB,port=7877}={}) {
  const app=express(),store=createStore(dbPath);let server;
  const route=handler=>(req,res,next)=>Promise.resolve().then(()=>handler(req,res)).catch(next);
  app.disable('x-powered-by');
  app.use((req,res,next)=>{
    const actual=server?.address()?.port??port;
    if(![`127.0.0.1:${actual}`,`localhost:${actual}`].includes(req.headers.host?.toLowerCase()))return res.status(403).json({error:'Localhost Host header required'});
    next();
  });
  app.get('/api/places',route((_req,res)=>res.json({schemaVersion:2,places:store.selectPlaces().map(p=>({...p,reviewCount:store.countReviews(p.placeId)}))})));
  app.get('/api/places/:placeId/reviews',route((req,res)=>{
    const limit=req.query.limit==null?50:Math.min(500,positiveNumber(req.query.limit,'limit',{integer:true,min:1}));
    const offset=req.query.offset==null?0:positiveNumber(req.query.offset,'offset',{integer:true,min:0});
    if(!store.selectPlaces().some(p=>p.placeId===req.params.placeId))return res.status(404).json({error:'Unknown place'});
    res.json({schemaVersion:2,placeId:req.params.placeId,total:store.countReviews(req.params.placeId),limit,offset,reviews:store.selectReviews({placeId:req.params.placeId,limit,offset})});
  }));
  app.get('/api/jobs',route((_req,res)=>res.json({schemaVersion:2,jobs:store.selectRecentJobs(20).map(j=>{
    const collected=j.items.reduce((n,i)=>n+(i.collectedCount??0),0),known=j.items.length&&j.items.every(i=>i.expectedCount!=null);
    const expected=known?j.items.reduce((n,i)=>n+i.expectedCount,0):null;
    return {id:j.id,status:j.status,notes:j.notes,createdAt:j.createdAt,counts:j.counts,collected,expected,completeness:expected>0?Math.min(1,collected/expected):expected===0&&j.status==='completed'?1:null};
  })})));
  app.get('/api/export/csv',route((req,res)=>res.type('text/csv; charset=utf-8').attachment('reviews.csv').send(toCsv(store.selectReviews({placeId:req.query.placeId}),undefined,{bom:true}))));
  app.get('/api/export/json',route((req,res)=>res.type('application/json; charset=utf-8').attachment('reviews.json').send(toJsonExport(store.selectReviews({placeId:req.query.placeId})))));
  app.use('/api',(_req,res)=>res.status(404).json({error:'Unknown API route'}));
  app.use('/static',express.static(path.join(PROJECT_ROOT,'src','dashboard','static')));
  app.get('/',(_req,res)=>res.sendFile(path.join(PROJECT_ROOT,'src','dashboard','static','index.html')));
  app.use((error,_req,res,_next)=>res.status(error.exitCode===64?400:500).json({error:redact(error.message)}));
  server=app.listen(port,'127.0.0.1',()=>console.log(`Dashboard: http://127.0.0.1:${server.address().port}`));
  server.once('close',()=>store.close());server.once('error',()=>store.close());
  return server;
}
