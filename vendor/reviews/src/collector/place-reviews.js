import fs from 'node:fs/promises';
import path from 'node:path';
import { SELECTORS } from './selectors.js';
import { normalizeReview } from '../core/normalize.js';
import { validateListingUrl, UsageError } from '../core/config.js';
import { extractPlaceId } from '../core/place-id.js';
import { classifyPage } from '../core/health.js';
import { decideTermination, itemStatusFor } from '../core/termination.js';
import { sleep, throwIfAborted } from '../core/cancel.js';
import { redact } from '../core/redact.js';
import { PROJECT_ROOT } from '../core/paths.js';

export const S = { container: SELECTORS.card, moreText: SELECTORS.moreText, reviewsTab: SELECTORS.reviewsTab, moreReviews: SELECTORS.moreReviews, sortButton: SELECTORS.sortButton };
export const DEFAULTS = { networkTimeoutMs: 60000, scrollIdleMs: 1500, expansionWaitMs: 250, expansionPasses: 8, placeIdWaitMs: 15000, maxDiagErrors: 40, stallTimeoutMs: 90000, hardTimeoutMs: 3600000 };
export function normalizePlaceUrl(raw,{hl='en',gl='us'}={}) {
  if(!validateListingUrl(raw))throw new TypeError('Not a recognized HTTP(S) Google Maps place/search URL');
  const url=new URL(raw);if(url.hostname==='maps.app.goo.gl')return {shortLink:url.href,canonical:null};
  url.searchParams.set('hl',hl);url.searchParams.set('gl',gl);
  return url.pathname.includes('/maps/search/')?{searchUrl:url.href,canonical:null}:{canonical:url.href};
}
// Self-contained: Playwright serializes this exact function. Tests run it on a real DOM.
export function extractInPage({card=null,selectors,seenIds=[],maxRecords=null}) {
  const clean=value=>{const text=String(value??'').replace(/\s+/g,' ').trim();return text||null;};
  // Google nests duplicate data-review-id wrappers (event divs, buttons) inside real cards.
  // Prefer the specific card selector, fall back to the bare attribute, and keep only outermost containers: drop any element whose own ancestor is also a card.
  const cardRoot=selectors.cardFallback??selectors.card;
  let all;
  if(card)all=[card];
  else{all=[...document.querySelectorAll(selectors.card)];
    if(!all.length&&cardRoot!==selectors.card)all=[...document.querySelectorAll(cardRoot)];
    all=all.filter(el=>!el.parentElement?.closest(cardRoot));}
  const seen=new Set(seenIds),sample=all.slice(0,20),coverage={reviewId:0,reviewerName:0,rating:0,publishedDateRaw:0};
  const extract=element=>{
    const owner=selectors.ownerResponse.map(s=>element.querySelector(s)).find(Boolean)??null;
    const find=(field,root=element,excludeOwner=false)=>{
      for(const selector of selectors[field])for(const node of root.querySelectorAll(selector))if(!excludeOwner||!owner?.contains(node))return node;
      return null;
    };
    const text=node=>{if(!node)return null;const clone=node.cloneNode(true);for(const button of clone.querySelectorAll('button,[role="button"]'))button.remove();return clean(clone.textContent);};
    const body=find('reviewText',element,true),stars=find('rating',element,true),date=find('publishedDateRaw',element,true),profile=find('reviewerProfileUrl',element,true);
    const ratingRaw=stars?.getAttribute('aria-label')??text(stars);
    const match=/^(?:rated\s+)?([1-5])(?:\.0)?\s*(?:stars?|\/\s*5|out of 5|sterne?|von 5)$/i.exec(ratingRaw?.trim()??'');
    const ownerDate=owner?find('ownerResponseDateRaw',owner):null,ownerBody=owner?find('reviewText',owner):null;
    let ownerResponse=text(ownerBody);
    if(owner&&!ownerBody){const clone=owner.cloneNode(true);for(const node of clone.querySelectorAll([...selectors.ownerResponseDateRaw,'button','[role="button"]'].join(',')))node.remove();ownerResponse=clean(clone.textContent)?.replace(/^(Response from the owner|Antwort vom Inhaber)\s*:?\s*/i,'')||null;}
    const reviewText=text(body),translation=element.querySelector('[data-is-english-language-translation],.NTyMbe');
    return {reviewId:element.getAttribute('data-review-id')||null,reviewerName:text(find('reviewerName',element,true)),reviewerProfileUrl:profile?.getAttribute('data-href')??profile?.getAttribute('href')??null,
      rating:match?Number(match[1]):null,ratingRaw,reviewText,originalLanguage:element.getAttribute('data-review-language')??body?.getAttribute('lang')??null,
      translatedByGoogle:translation?(translation.getAttribute('data-is-english-language-translation')!=='false'):null,
      publishedDateRaw:text(date)??date?.getAttribute('datetime')??null,ownerResponse,ownerResponseDateRaw:text(ownerDate)??ownerDate?.getAttribute('datetime')??null,
      textTruncated:Number(/(?:…|\.{3})\s*$/.test(reviewText??'')||/(?:…|\.{3})\s*$/.test(ownerResponse??''))};
  };
  const cache=new Map();for(const element of sample){const r=extract(element);cache.set(element,r);for(const field of Object.keys(coverage))if(r[field]!=null)coverage[field]++;}
  const reviews=[];for(const element of all){const id=element.getAttribute('data-review-id');if(id&&seen.has(id))continue;if(maxRecords!=null&&reviews.length>=maxRecords)break;reviews.push(cache.get(element)??extract(element));}
  return {reviews,cardCount:all.length,fieldCoverage:Object.fromEntries(Object.entries(coverage).map(([k,v])=>[k,sample.length?v/sample.length:null])),sampleSize:sample.length};
}
export function expandInPage({selectors}) {
  let count=0;
  const root=selectors.cardFallback??selectors.card;
  let cards=[...document.querySelectorAll(selectors.card)];
  if(!cards.length)cards=[...document.querySelectorAll(root)];
  cards=cards.filter(el=>!el.parentElement?.closest(root));
  for(const card of cards)for(const button of [...card.querySelectorAll(selectors.moreText)]){
    const label=button.getAttribute('aria-label')??button.textContent??'';
    if(label==='More'||button.getAttribute('aria-expanded')==='true'||/^(less|weniger)$/i.test(label.trim()))continue;
    button.click();count++;
  }
  return count;
}
export function pickPlaceRatingInPage({selectors}) {
  for(const selector of selectors.placeRating)for(const node of document.querySelectorAll(selector)){
    const text=(node.getAttribute('aria-label')??node.textContent??'').trim();
    const m=/^([1-5](?:[.,]\d+)?)\s*(?:stars?|sterne?)?$/i.exec(text);
    if(m&&Number(m[1].replace(',','.'))<=5)return Number(m[1].replace(',','.'));
  }
  return null;
}
export function readSurfaceInPage({selectors}) {
  const body=(document.body?.innerText??document.body?.textContent??'').slice(0,2048);
  let expected=null;
  for(const node of document.querySelectorAll(selectors.reviewsTab+','+selectors.moreReviews)){
    const label=node.getAttribute('aria-label')??node.textContent??'';const match=/(\d[\d.,\s\u202f]*)/.exec(label);
    if(match&&!/[kmb]\b/i.test(label.slice(match.index+match[0].length))){expected=Number(match[1].replace(/\D/g,''));break;}
  }
  const leaves=[...document.querySelectorAll('span,div,[role="status"]')].filter(n=>!n.children.length).map(n=>(n.textContent??'').trim());
  const cardRoot=selectors.cardFallback??selectors.card;
  const firstCard=[...document.querySelectorAll(cardRoot)].find(el=>!el.parentElement?.closest(cardRoot))??null;
  const reviewFeed=firstCard?.closest(selectors.feed)??firstCard?.parentElement;
  const endMarkerSeen=!!reviewFeed&&[...reviewFeed.querySelectorAll('span,div,[role="status"]')]
    .filter(node=>!node.children.length&&!node.closest(cardRoot))
    .some(node=>/^(you(?:’|')ve reached the end(?: of the list)?|no more reviews|keine weiteren rezensionen)[.!]?$/i.test((node.textContent??'').trim()));
  // A short place may never render the end-marker text. Detect pagination end from the
  // feed's real scroll container: first ancestor whose CSS overflow actually scrolls. When
  // that container is at its bottom, or no scrolling ancestor exists because all reviews
  // fit on screen, the feed is exhausted — the stall decision can treat it as complete.
  let feedAtEnd=false;
  if(reviewFeed){
    let scroller=null;
    for(let node=reviewFeed;node;node=node.parentElement){
      if(node.clientHeight>100){
        const overflowY=getComputedStyle(node).overflowY;
        if(overflowY==='auto'||overflowY==='scroll'){scroller=node;break;}
      }
    }
    const bottomDist=n=>n.scrollHeight-(n.scrollTop+n.clientHeight);
    feedAtEnd=scroller?bottomDist(scroller)<80:bottomDist(document.scrollingElement??document.documentElement)<80;
  }
  return {body,expected,recaptchaIframe:!!document.querySelector('iframe[src*="recaptcha"],iframe[title*="recaptcha" i]'),consentForm:!!document.querySelector('form[action*="consent.google"]'),
    spinnerVisible:[...document.querySelectorAll('[role="progressbar"],[aria-busy="true"]')].some(n=>!n.hidden&&n.getAttribute('aria-hidden')!=='true'),
    endMarkerSeen,
    feedAtEnd,
    noReviewsDetected:expected===0||!firstCard&&leaves.some(t=>/^(no reviews(?: yet)?|noch keine rezensionen|keine bewertungen)(?:\.|!)?$/i.test(t)),
    name:[...document.querySelectorAll('h1')].map(n=>n.textContent.trim()).find(t=>t&&!/^(results|ergebnisse|sponsored|gesponsert)$/i.test(t))??null};
}
export function scrollInPage({selectors,up=false}) {
  const cardRoot=selectors.cardFallback??selectors.card;
  const card=[...document.querySelectorAll(cardRoot)].find(el=>!el.parentElement?.closest(cardRoot))??null;
  const anchor=card??[...document.querySelectorAll('h1')].find(node=>! /^(results|ergebnisse|sponsored|gesponsert)$/i.test(node.textContent.trim()));
  if(!anchor)return;
  let scroller=card?.closest(selectors.feed)??anchor.parentElement;
  for(let node=anchor.parentElement;node;node=node.parentElement)if(node.scrollHeight>node.clientHeight+100&&node.clientHeight>100){scroller=node;break;}
  if(scroller)scroller.scrollTop=up?0:scroller.scrollHeight;
}
export function sortPattern(mode) {
  const patterns={newest:/newest|neueste/i,relevant:/relevant/i,highest:/highest|höchste|beste/i,lowest:/lowest|niedrigste|schlechteste/i};
  if(!patterns[mode])throw new UsageError('sort must be newest|relevant|highest|lowest|default');return patterns[mode];
}
export async function applySort(page,mode,{wait=sleep,signal}={}) {
  if(!mode||mode==='default')return true;
  const pattern=sortPattern(mode);
  for(let attempt=0;attempt<2;attempt++){
    throwIfAborted(signal);
    try{
      await page.locator(SELECTORS.sortButton).first().click({timeout:5000});
      const option=page.locator('[role="menuitemradio"]').filter({hasText:pattern}).first();
      const alreadyChecked=await option.getAttribute('aria-checked',{timeout:1000}).then(v=>v==='true').catch(()=>false);
      await option.click({timeout:5000});
      const liveText=await page.evaluate(()=>[...document.querySelectorAll('[aria-live]')].map(n=>n.textContent??'').join(' ')).catch(()=>'');
      const verified=alreadyChecked
        ||await option.getAttribute('aria-checked',{timeout:1000}).then(v=>v==='true').catch(()=>false)
        ||pattern.test(await page.locator(SELECTORS.sortButton).first().getAttribute('aria-label').catch(()=>''))
        ||pattern.test(await page.locator(SELECTORS.sortButton).first().textContent().catch(()=>''))
        ||pattern.test(liveText);
      if(verified){
        // Wait for card identity to settle after the control confirms the sort.
        await page.waitForSelector(SELECTORS.card,{timeout:15000}).catch(()=>{});
        let prior=null,stable=0;
        for(let poll=0;poll<16;poll++){await wait(250,signal);const id=await page.locator(SELECTORS.card).first().getAttribute('data-review-id',{timeout:1000}).catch(()=>null);stable=id&&id===prior?stable+1:0;prior=id;if(stable>=2)return true;}
        if(await page.locator(SELECTORS.card).count())return true;
      }
    }catch(error){throwIfAborted(signal);}
  }
  return false;
}
async function handleConsent(page,cfg,diag) {
  const state=await page.evaluate(readSurfaceInPage,{selectors:SELECTORS});
  if(classifyPage(page.url(),{text:state.body,consentForm:state.consentForm})!=='consent-wall')return true;
  diag.consentScreens++;
  const reject=page.getByRole('button',{name:/^(Reject all|Alle ablehnen)$/i});
  const accept=page.getByRole('button',{name:/^(Accept all|Alle akzeptieren|I agree|Ich stimme zu)$/i});
  try{if(await reject.count())await reject.first().click({timeout:10000});else await accept.first().click({timeout:10000});
    await page.waitForURL(url=>url.hostname!=='consent.google.com',{timeout:10000});return true;
  }catch{throwIfAborted(cfg.signal);return false;}
}
async function resolveSearch(page) {
  if(!/\/maps\/search\//.test(page.url()))return true;
  // A search may already display a single place panel.
  if(await page.locator(SELECTORS.reviewsTab).count())return true;
  if(/\/maps\/place\//.test(page.url()))return true;
  await page.waitForSelector('a[href*="/maps/place/"],div[role="feed"] a',{timeout:15000}).catch(()=>{});
  if(/\/maps\/place\//.test(page.url()))return true;
  let query='';try{query=decodeURIComponent(new URL(page.url()).pathname.split('/maps/search/')[1]?.split('/')[0]??'').replace(/\+/g,' ');}catch{}
  const tokens=query.toLowerCase().split(/\s+/).filter(Boolean);
  const links=await page.evaluate(()=>[...document.querySelectorAll('a[href*="/maps/place/"]')].slice(0,25).map((node,idx)=>({idx,name:node.getAttribute('aria-label')??node.textContent??'',sponsored:!!node.closest('[aria-label*="Sponsored" i],[aria-label*="Gesponsert" i]')})));
  const ranked=links.map(link=>({...link,score:link.sponsored?-1:tokens.filter(t=>link.name.toLowerCase().includes(t)).length})).sort((a,b)=>b.score-a.score);
  if(!ranked[0]||ranked[0].score<Math.max(1,Math.floor(tokens.length*.4)))return /\/maps\/place\//.test(page.url());
  await page.locator('a[href*="/maps/place/"]').nth(ranked[0].idx).click({timeout:10000});
  await page.waitForURL(/\/maps\/place\//,{timeout:15000}).catch(()=>{});return /\/maps\/place\//.test(page.url());
}
async function resolveFeatureId(page,cfg) {
  const end=cfg.now()+cfg.placeIdWaitMs;
  do{throwIfAborted(cfg.signal);const id=extractPlaceId(page.url());if(id)return id;
    const hrefs=await page.evaluate(()=>[...document.querySelectorAll('a[href*="!1s"],a[href*="%211s"]')].map(n=>n.href));
    for(const href of hrefs){const id=extractPlaceId(href);if(id)return id;}
    if(cfg.now()>=end)break;await cfg.wait(250,cfg.signal);
  }while(cfg.now()<end);
  return null;
}
export async function captureDiagnostics(page,{jobId='unassigned',idx=0,reason,diagnosticsDir=path.join(PROJECT_ROOT,'data','diagnostics')}={}) {
  const safe=s=>String(s).replace(/[^A-Za-z0-9_-]/g,'_');const directory=path.join(diagnosticsDir,safe(jobId));await fs.mkdir(directory,{recursive:true});
  const base=path.join(directory,`${idx}-${safe(reason)}`),artifacts={};
  const host=new URL(page.url()).hostname;
  if(host==='accounts.google.com')return {omitted:'Authentication page content omitted'};
  try{await page.screenshot({path:base+'.png',mask:[page.locator('input,form[action*="signin"],a[aria-label*="Google Account" i],a[aria-label*="Google-Konto" i]')]});artifacts.screenshot=base+'.png';}catch(error){artifacts.screenshotError=redact(error.message);}
  try{const html=await page.evaluate(()=>{const root=document.documentElement.cloneNode(true);for(const node of root.querySelectorAll('script,style,input,textarea,form,a[aria-label*="Google Account" i],a[aria-label*="Google-Konto" i]'))node.remove();for(const node of root.querySelectorAll('*'))for(const attr of [...node.attributes])if(/token|secret|password|authorization|cookie|^on/i.test(attr.name))node.removeAttribute(attr.name);return root.outerHTML;});await fs.writeFile(base+'.html',Buffer.from(redact(html)).subarray(0,262144));artifacts.html=base+'.html';}catch(error){artifacts.htmlError=redact(error.message);}
  return artifacts;
}
export function finalizeRecord(raw,cfg={},place={}) {
  if(!raw?.reviewId)return null;
  const reviewUrl=place.placeId?`https://www.google.com/maps/place/?data=!1s${encodeURIComponent(place.placeId)}!8s${encodeURIComponent(raw.reviewId)}&hl=${cfg.hl??'en'}&gl=${cfg.gl??'us'}`:null;
  return normalizeReview({...raw,reviewUrl},{placeId:place.placeId,now:cfg.now?.()??Date.now()}).record;
}
export async function scrapePlaceReviews(page,input,onProgress=async()=>{}) {
  const overrides=input.overrides??{},cfg={...DEFAULTS,...overrides,...input.language,signal:input.signal??overrides.signal,now:overrides.now??Date.now,wait:overrides.sleep??sleep};
  cfg.stallTimeoutMs=overrides.stallTimeoutSec!=null?overrides.stallTimeoutSec*1000:cfg.stallTimeoutMs;
  cfg.hardTimeoutMs=overrides.placeTimeoutMin!=null?overrides.placeTimeoutMin*60000:cfg.hardTimeoutMs;
  const started=cfg.now(),seen=new Set(),reviews=[],diag={moreClicks:0,expandClicks:0,consentScreens:0,staleElements:0,pageErrors:[],fieldCoverage:{},authState:cfg.authState??'unknown',sortApplied:null};
  const place={placeId:null,name:null,reviewsCount:null,rating:null,url:null};
  let reason='continue',detail=null,surface,lastProgress=started,recoveryDone=false,endMarkerSeen=false;
  const pageError=error=>{if(diag.pageErrors.length<cfg.maxDiagErrors)diag.pageErrors.push(redact(error.message));};page.on?.('pageerror',pageError);
  const end=async()=>{
    const termination={reason,detail,authState:diag.authState,sortApplied:diag.sortApplied,endMarkerSeen,collectedCount:reviews.length,expected:place.reviewsCount,completeness:place.reviewsCount>0?Math.min(1,reviews.length/place.reviewsCount):null,durationMs:cfg.now()-started};
    itemStatusFor(reason,{collected:reviews.length});
    if(!['limit-reached','no-more-reviews','no-reviews','skipped-incremental'].includes(reason))diag.artifacts=await captureDiagnostics(page,{...cfg,reason});
    return {place,reviews,termination,diagnostics:diag};
  };
  try{
    throwIfAborted(cfg.signal);
    const normalized=normalizePlaceUrl(input.url,cfg);await page.goto(normalized.canonical??normalized.searchUrl??normalized.shortLink,{waitUntil:'domcontentloaded',timeout:cfg.networkTimeoutMs});
    if(!await handleConsent(page,cfg,diag)){reason='consent-wall';return await end();}
    surface=await page.evaluate(readSurfaceInPage,{selectors:SELECTORS});
    let health=classifyPage(page.url(),{text:surface.body,recaptchaIframe:surface.recaptchaIframe});
    if(health!=='ok'){reason=health;return await end();}
    if(!await resolveSearch(page)){reason='search-mismatch';return await end();}
    await page.waitForSelector(`h1,${SELECTORS.reviewsTab},${SELECTORS.card}`,{timeout:15000}).catch(()=>{});
    place.placeId=await resolveFeatureId(page,cfg);place.url=page.url();
    if(!place.placeId){reason='missing-place-id';return await end();}
    surface=await page.evaluate(readSurfaceInPage,{selectors:SELECTORS});place.name=surface.name;place.reviewsCount=surface.expected;place.rating=await page.evaluate(pickPlaceRatingInPage,{selectors:SELECTORS});
    if(cfg.incremental&&cfg.isPlaceCollected?.(place.placeId)){reason='skipped-incremental';return await end();}
    if(surface.noReviewsDetected){reason='no-reviews';return await end();}
    const tab=page.locator(SELECTORS.reviewsTab).first();
    if(await tab.count()){await tab.click({timeout:10000});await page.waitForSelector(SELECTORS.card,{timeout:10000}).catch(()=>{});}
    else if(!await page.locator(SELECTORS.card).count()){
      const more=page.locator(SELECTORS.moreReviews).first();if(await more.count()){await more.click({timeout:10000});await page.waitForSelector(SELECTORS.card,{timeout:10000}).catch(()=>{});}
    }
    health=classifyPage(page.url());
    if(health!=='ok'){reason=health==='sign-in-wall'&&diag.authState==='anonymous'?'sign-in-required':health;return await end();}
    // A requested sort needs mounted cards; some places only mount the first cards once the feed is
    // scrolled, so scroll-and-recheck before giving up — never click Sort against an empty panel.
    if(input.sortMode&&input.sortMode!=='default'&&!await page.locator(SELECTORS.card).count()){
      let cardLoaded=false;
      for(let i=0;i<3&&!cardLoaded;i++){
        cardLoaded=!!await page.waitForSelector(SELECTORS.card,{timeout:8000}).catch(()=>null);
        if(!cardLoaded){await page.evaluate(scrollInPage,{selectors:SELECTORS});await page.mouse.wheel(0,2500);await cfg.wait(cfg.scrollIdleMs,cfg.signal);}
      }
      if(!cardLoaded){
        surface=await page.evaluate(readSurfaceInPage,{selectors:SELECTORS});
        reason=surface.noReviewsDetected?'no-reviews':'pagination-stall';detail='No review cards loaded after clicking the Reviews tab';
      }
    }
    if(reason==='continue'){
      if(!await applySort(page,input.sortMode,{wait:cfg.wait,signal:cfg.signal})){
        reason=classifyPage(page.url())==='sign-in-wall'&&diag.authState==='anonymous'?'sign-in-required':'sort-failed';detail='Requested sort could not be verified after two attempts';return await end();
      }
      diag.sortApplied=input.sortMode??'default';
    }
    while(reason==='continue'){
      throwIfAborted(cfg.signal);surface=await page.evaluate(readSurfaceInPage,{selectors:SELECTORS});
      health=classifyPage(page.url(),{text:surface.body,recaptchaIframe:surface.recaptchaIframe,consentForm:surface.consentForm});
      if(health!=='ok'){reason=health==='sign-in-wall'&&diag.authState==='anonymous'?'sign-in-required':health;break;}
      if(surface.expected!=null)place.reviewsCount=surface.expected;
      for(let pass=0;pass<cfg.expansionPasses;pass++){const clicks=await page.evaluate(expandInPage,{selectors:SELECTORS});diag.expandClicks+=clicks;if(!clicks)break;await cfg.wait(cfg.expansionWaitMs,cfg.signal);}
      const batch=await page.evaluate(extractInPage,{selectors:SELECTORS,seenIds:[...seen],maxRecords:input.maxReviews==null?null:Math.max(0,input.maxReviews-reviews.length)});
      diag.fieldCoverage=batch.fieldCoverage;
      const failing=Object.entries(batch.fieldCoverage).find(([,coverage])=>coverage!=null&&coverage<.9);
      if(failing){reason='structure-drift';detail=`${failing[0]} coverage ${Math.round(failing[1]*100)}%; strategies: ${JSON.stringify(SELECTORS[failing[0]]??SELECTORS.card)}`;break;}
      const fresh=[];
      for(const raw of batch.reviews){const rec=finalizeRecord(raw,cfg,place);if(!rec||seen.has(rec.reviewId))continue;seen.add(rec.reviewId);rec.feedRank=reviews.length+1;reviews.push(rec);fresh.push(rec);}
      if(fresh.length){lastProgress=cfg.now();recoveryDone=false;await onProgress('stream-batch',{place,reviews:fresh});}
      await onProgress('page-batch',{fresh:fresh.length,total:reviews.length});
      endMarkerSeen=surface.endMarkerSeen;
      reason=decideTermination({collected:reviews.length,expected:place.reviewsCount,limit:input.maxReviews,authState:diag.authState,endMarkerSeen,feedAtEnd:surface.feedAtEnd,noReviewsDetected:surface.noReviewsDetected,minCompleteness:cfg.minCompleteness??.9,elapsedMs:cfg.now()-started,hardTimeoutMs:cfg.hardTimeoutMs,stalled:!fresh.length,stalledForMs:cfg.now()-lastProgress,stallTimeoutMs:cfg.stallTimeoutMs,recoveryDone,spinnerVisible:surface.spinnerVisible});
      if(reason!=='continue')break;
      if(!fresh.length&&!recoveryDone&&cfg.now()-lastProgress>=Math.min(10000,cfg.stallTimeoutMs/2)){
        if(await tab.count())await tab.click({timeout:3000}).catch(()=>{});
        await page.evaluate(scrollInPage,{selectors:SELECTORS,up:true});await cfg.wait(cfg.scrollIdleMs,cfg.signal);recoveryDone=true;
      }
      await page.evaluate(scrollInPage,{selectors:SELECTORS});await page.mouse.wheel(0,2500);await cfg.wait(cfg.scrollIdleMs,cfg.signal);
    }
    if(['limit-reached','no-more-reviews'].includes(reason)&&reviews.some(r=>r.textTruncated)){reason='incomplete';detail='Review or owner-response text remains truncated';}
    if(!reviews.length&&['pagination-stall','anonymous-preview-limit'].includes(reason)){
      if(diag.authState==='anonymous'&&place.placeId){
        reason='anonymous-preview-limit';detail='Anonymous preview limited review access; zero cards mounted';
      }else{
        reason='structure-unknown';detail='No usable review cards appeared; zero reviews was not confirmed';
      }
    }
    return await end();
  }finally{page.off?.('pageerror',pageError);}
}
