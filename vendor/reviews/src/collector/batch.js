import { chromium as defaultChromium } from 'rebrowser-playwright';
import { scrapePlaceReviews as defaultScrape } from './place-reviews.js';
import { getProfileDir, hasSavedProfile, launchWithFallback, detectAuthState, cloneProfileForWorker, cleanupWorkerProfile } from './browser.js';
import { withRetry } from '../core/retry.js';
import { PROJECT_ROOT } from '../core/paths.js';
import { extractPlaceId } from '../core/place-id.js';
import { parseRunOptions, UsageError } from '../core/config.js';
import { itemStatusFor } from '../core/termination.js';
import { sleep, throwIfAborted, isAbort, closeWithTimeout } from '../core/cancel.js';
import { redact } from '../core/redact.js';

export function isTransient(error) {return error?.name==='TimeoutError'||/net::ERR_[A-Z_]+|\bERR_(CONNECTION|NETWORK|TIMED_OUT|NAME_NOT_RESOLVED)|Target (page, context or browser has been closed|closed)|Navigation.*timed out/i.test(String(error?.message));}
export async function launchBatchCollector(inputs, options={}, onComplete=async()=>({}), onBatch=async()=>{}, deps={}) {
  const config=parseRunOptions(options), signal=config.signal;
  const sanitize=value=>redact(value,[config.proxyConfig?.username,config.proxyConfig?.password,...(config.proxyPool??[]).flatMap(p=>[p.username,p.password])]);
  const chromium=deps.chromium??defaultChromium,scrape=deps.scrapePlaceReviews??defaultScrape,wait=deps.sleep??sleep;
  const profileExists=deps.hasSavedProfile??hasSavedProfile,projectRoot=deps.projectRoot??PROJECT_ROOT;
  const items=inputs.map((v,idx)=>typeof v==='string'?{url:v,idx}:v),summary=[],remaining=[];
  const complete=async(result,item,attempts,started)=>{
    const base={listingUrl:item.url,idx:item.idx,placeId:result.place?.placeId??null,placeName:result.place?.name??null,status:itemStatusFor(result.termination.reason,{collected:result.reviews?.length??0}),collected:result.reviews?.length??0,expected:result.place?.reviewsCount??null,termination:result.termination,error:result.error??null,attempts,durationMs:Date.now()-started};
    try {return {...base,...await onComplete(result,item.url,item.idx,attempts),attempts,durationMs:Date.now()-started};}
    catch(error){return {...base,status:'failed',error:sanitize(error.message),termination:{reason:'failed',detail:'Completion callback failed: '+sanitize(error.message)}};}
  };
  for(const item of items){const placeId=extractPlaceId(item.url);if(config.incremental&&placeId&&config.isPlaceCollected?.(placeId))summary.push(await complete({place:{placeId},reviews:[],termination:{reason:'skipped-incremental',authState:'unknown'}},item,0,Date.now()));else remaining.push(item);}
  if(!remaining.length||signal?.aborted)return summary;
  const profileName=config.profile===false?null:typeof config.profile==='string'?config.profile:profileExists(projectRoot,'default')?'default':null;
  const profileDir=profileName?getProfileDir(projectRoot,profileName):null;
  let concurrency=config.concurrency;
  const useProfilePool=Boolean(profileDir&&concurrency>1&&config.profilePool);
  if(profileDir&&concurrency>1&&!config.unsafeConcurrency&&!useProfilePool){console.warn('Persistent profiles use concurrency 1; --unsafe-concurrency is required to override.');concurrency=1;}
  let proxyIdx=0;
  const getNextProxy=()=>{
    if(!config.proxyPool?.length)return config.proxyConfig;
    const p=config.proxyPool[proxyIdx%config.proxyPool.length];
    proxyIdx++;
    return p;
  };
  let {resource,channel}=await launchWithFallback(chromium,profileDir,{...config,proxyConfig:getNextProxy()});
  console.log(`Browser: ${channel}; ${profileDir?(useProfilePool?'profile pool ('+profileName+', '+concurrency+' workers)':'persistent profile '+profileName):'anonymous context'}`);
  let browser=profileDir?null:resource,sharedContext=profileDir?resource:null;
  const contexts=new Set(),resources=new Set([resource]),clonedDirs=new Set();
  let closing,closed=false,consecutiveBlocks=0,circuitOpen=false,position=0,schedule=Promise.resolve();
  const closeAll=()=>{
    if(closing)return closing;
    closing=closeWithTimeout(async()=>{
      const results=await Promise.allSettled([...contexts].map(c=>c.close()));
      await Promise.allSettled([...resources].map(r=>r.close()));
      for(const dir of clonedDirs)(deps.cleanupWorkerProfile??cleanupWorkerProfile)(dir);
      const failed=results.find(r=>r.status==='rejected');if(failed&&!signal?.aborted)throw failed.reason;closed=true;
    },10000);
    return closing;
  };
  const onAbort=()=>{closeAll().catch(error=>console.error(sanitize(error.message)));};
  signal?.addEventListener('abort',onAbort,{once:true});
  async function takeNext(){const ticket=schedule.then(async()=>{
    if(signal?.aborted||circuitOpen||position>=remaining.length)return null;
    if(position>0){const [min,max]=config.delayMs;await wait(min+Math.floor(Math.random()*(max-min+1)),signal);}
    if(signal?.aborted||circuitOpen)return null;return remaining[position++];
  });schedule=ticket.catch(()=>{});return ticket;}
  let authState='unknown';
  try {
    const probeContext=sharedContext??await browser.newContext({locale:config.language});
    if(!sharedContext)contexts.add(probeContext);
    try{authState=await (deps.detectAuthState??detectAuthState)(probeContext,{signal,language:config.language,region:config.region});}
    finally{if(!sharedContext){await probeContext.close();contexts.delete(probeContext);}}
    console.log(`Authentication: ${authState}`);if(authState==='anonymous')console.warn('ANONYMOUS: Google restricts unauthenticated access; reviews may be limited to a preview or entirely unavailable. Use gmr login for full collection.');
    await config.onAuthState?.(authState);
    if(config.requireLogin&&authState!=='signed-in')throw new UsageError('Signed-in Google Maps profile required. Run gmr login, then gmr doctor.');
    if(useProfilePool&&sharedContext){await sharedContext.close().catch(()=>{});resources.delete(resource);sharedContext=null;}
    async function work(wIdx=0){
      let workerResource=null,workerSharedContext=null,workerProfileDir=null;
      if(useProfilePool){
        workerProfileDir=(deps.cloneProfileForWorker??cloneProfileForWorker)(profileDir,wIdx);
        clonedDirs.add(workerProfileDir);
        const launched=await launchWithFallback(chromium,workerProfileDir,{...config,proxyConfig:getNextProxy()});
        workerResource=launched.resource;resources.add(workerResource);workerSharedContext=workerResource;
      }
      try{while(true){let item;try{item=await takeNext();}catch(error){if(isAbort(error,signal))return;throw error;}if(!item)return;
        const started=Date.now();let context=workerSharedContext??sharedContext,page,result,attempts=0;
        try{
          result=await withRetry(async attempt=>{
            attempts=attempt;throwIfAborted(signal);
            if(!context){context=await browser.newContext({locale:config.language,viewport:{width:1400,height:960},proxy:getNextProxy()});contexts.add(context);}
            try{
              page=await context.newPage();
              return await scrape(page,{url:item.url,sortMode:config.sort,maxReviews:config.limit,language:{hl:config.language,gl:config.region},overrides:{...config,idx:item.idx,authState},signal},async(event,data)=>{
                if(event==='stream-batch'){try{await onBatch(data,item.url,item.idx);}catch(error){error.persistenceError=true;throw error;}}
                else if(['sort-failed','sort-missing'].includes(event))console.warn(sanitize(`${event}: ${JSON.stringify(data)}`));
              });
            }catch(error){
              if(isAbort(error,signal))throw error;
              if(error.persistenceError||!isTransient(error))throw error;
              if(/Target .*closed|has been closed/i.test(error.message)){
                if(workerSharedContext){
                  await workerSharedContext.close().catch(()=>{});resources.delete(workerResource);
                  const replacement=await launchWithFallback(chromium,workerProfileDir,{...config,proxyConfig:getNextProxy()});
                  workerResource=replacement.resource;resources.add(workerResource);workerSharedContext=workerResource;context=workerSharedContext;
                }else if(sharedContext){
                  const staleContext=sharedContext;
                  await staleContext.close().catch(()=>{});resources.delete(staleContext);
                  const replacement=await launchWithFallback(chromium,profileDir,{...config,proxyConfig:getNextProxy()});
                  resource=replacement.resource;resources.add(resource);sharedContext=resource;context=sharedContext;
                }else{await context.close().catch(()=>{});contexts.delete(context);context=null;}
              }
              throw error;
            }finally{if(page){await page.close().catch(()=>{});page=null;}}
          },{maxAttempts:3,baseDelayMs:1000,signal,wait,retryableError:error=>!error.persistenceError&&isTransient(error),onRetry:({attempt,error})=>console.warn(sanitize(`Retry ${attempt}/3: ${error.message}`))});
        }catch(error){result={place:null,reviews:[],error:sanitize(error.message),termination:{reason:isAbort(error,signal)?'interrupted':error.persistenceError?'persistence-error':'failed',detail:sanitize(error.message),authState}};}
        finally{if(context&&!workerSharedContext&&!sharedContext){await context.close().catch(()=>{});contexts.delete(context);}}
        result.termination={...result.termination,authState};
        const done=await complete(result,item,attempts,started);summary.push(done);
        consecutiveBlocks=['blocked','captcha'].includes(result.termination.reason)?consecutiveBlocks+1:0;
        if(consecutiveBlocks>=2){circuitOpen=true;console.error('Two consecutive blocks: stopping; unstarted places remain pending.');}
      }}
      finally{
        if(workerSharedContext){await workerSharedContext.close().catch(()=>{});resources.delete(workerResource);}
        if(workerProfileDir){clonedDirs.delete(workerProfileDir);(deps.cleanupWorkerProfile??cleanupWorkerProfile)(workerProfileDir);}
      }
    }
    const settled=await Promise.allSettled(Array.from({length:concurrency},(_,i)=>work(i)));
    for(const res of settled){if(res.status==='rejected'&&!isAbort(res.reason,signal))throw res.reason;}
    return summary.sort((a,b)=>a.idx-b.idx);
  } finally {
    signal?.removeEventListener('abort',onAbort);
    if(!closed)await closeAll();
  }
}
