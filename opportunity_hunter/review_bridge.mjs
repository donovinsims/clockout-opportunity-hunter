// Adapter around the reviewed collector API; no upstream CLI/server is started.
import fs from 'node:fs';
import { REVIEW_LAUNCH_SECURITY } from './review_browser_options.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '../vendor/reviews/node_modules/rebrowser-playwright/index.mjs';
import { scrapePlaceReviews } from '../vendor/reviews/src/collector/place-reviews.js';
import { checkReviewAuth } from './review_auth.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const requestPath=path.resolve(process.argv[2]);
if(!requestPath.startsWith(root+path.sep))throw new Error('Request must stay inside project');
const req=JSON.parse(fs.readFileSync(requestPath,'utf8'));
const output=path.resolve(req.output);
if(!output.startsWith(root+path.sep))throw new Error('Output must stay inside project');
const started=Date.now(), controller=new AbortController();
let browser,context,page;
let state={checked_at:new Date().toISOString(),status:'running',place:{},reviews:[],termination:{reason:'running'},auth_state:'unknown'};
const safeReview=r=>Object.fromEntries(['reviewId','rating','ratingRaw','reviewText','publishedDateRaw','publishedDateParsed','publishedDateEarliest','publishedDateLatest','datePrecision','ownerResponse','ownerResponseDateRaw','reviewUrl','textTruncated','feedRank','originalLanguage','translatedByGoogle'].map(k=>[k,r[k]??null]));
function save(){const tmp=output+'.tmp';fs.writeFileSync(tmp,JSON.stringify({...state,elapsed_seconds:(Date.now()-started)/1000},null,2),{mode:0o600});fs.renameSync(tmp,output);}
const abort=()=>{controller.abort();page?.close().catch(()=>{});if(req.anonymous)context?.close().catch(()=>{});};
process.on('SIGTERM',abort);process.on('SIGINT',abort);
try{
  if(req.anonymous){
    browser=await chromium.launch({channel:'chrome',headless:!req.visible,...REVIEW_LAUNCH_SECURITY,timeout:15000});
    const probe=await browser.newContext(),p=await probe.newPage();
    const ua=(await p.evaluate(()=>navigator.userAgent)).replace('HeadlessChrome/','Chrome/');await probe.close();
    context=await browser.newContext({locale:'en-US',viewport:{width:1400,height:960},acceptDownloads:false,serviceWorkers:'block',userAgent:ua});
  }else{
    const address=new URL(req.endpoint);
    if(address.protocol!=='http:'||address.hostname!=='127.0.0.1'||!address.port)throw new Error('Dedicated loopback Chrome session required');
    browser=await chromium.connectOverCDP(req.endpoint,{timeout:15000});
    context=browser.contexts()[0];
  }
  if(context){
    state.auth_state=req.anonymous?'anonymous':await checkReviewAuth(context);
    if(req.mode==='doctor'){
      state.status=state.auth_state==='signed-in'?'ready':'needs_login';state.termination={reason:'auth-check'};save();
    }else if(!req.anonymous&&state.auth_state!=='signed-in'){
      state.status='needs_login';state.termination={reason:'sign-in-required'};save();process.exitCode=2;
    }else{
      page=await context.newPage();
      await page.goto(req.url,{waitUntil:'domcontentloaded',timeout:15000});
      await page.locator('h1.DUwDvf, h1.fontHeadlineLarge').first().waitFor({timeout:8000}).catch(()=>{});
      const listingPhone=await page.locator('button[data-item-id*="phone"]').first().getAttribute('aria-label').catch(()=>'');
      const digits=v=>String(v??'').replace(/\D/g,'').slice(-10);
      state.identity_phone_verified=Boolean(req.phone&&digits(listingPhone)===digits(req.phone));
      if(req.phone&&!state.identity_phone_verified){
        state.status='identity_review';state.termination={reason:'phone-mismatch-or-unavailable'};save();
      }else{
      const result=await scrapePlaceReviews(page,{url:req.url,maxReviews:req.limit,sortMode:req.sort??'newest',language:{hl:'en',gl:'us'},signal:controller.signal,
        overrides:{authState:state.auth_state,networkTimeoutMs:15000,placeIdWaitMs:8000,hardTimeoutMs:req.timeout*1000,stallTimeoutMs:10000,scrollIdleMs:1000,
                   diagnosticsDir:path.dirname(output),jobId:'diagnostics',idx:0}},async(event,data)=>{
        if(event==='stream-batch'){
          state.place=data.place;
          const reviews=new Map(state.reviews.map(r=>[r.reviewId,r]));
          for(const r of data.reviews)if(r.reviewId)reviews.set(r.reviewId,safeReview(r));
          state.reviews=[...reviews.values()].slice(0,req.limit);save();
        }
      });
      state={...state,place:result.place,reviews:result.reviews.map(safeReview).slice(0,req.limit),termination:result.termination,
             status:['limit-reached','no-more-reviews','no-reviews'].includes(result.termination.reason)?'collected':'incomplete'};
      save();
      }
    }
  }
}catch(error){state.status=state.reviews.length?'incomplete':'failed';state.termination={reason:controller.signal.aborted?'interrupted':'collector-error',error_type:error.name};save();process.exitCode=1;}
finally{
  await page?.close().catch(()=>{});
  if(req.anonymous){await context?.close().catch(()=>{});await browser?.close().catch(()=>{});}
  process.off('SIGTERM',abort);process.off('SIGINT',abort);
  // For attached Chrome, exiting disconnects this client without closing the user's browser.
  if(!req.anonymous)process.exit(process.exitCode??0);
}
