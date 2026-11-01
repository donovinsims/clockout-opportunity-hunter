import path from 'node:path';
import { REVIEW_LAUNCH_SECURITY } from '../../../../opportunity_hunter/review_browser_options.mjs';
import fs from 'node:fs';
import { chromium } from 'rebrowser-playwright';
import { PROJECT_ROOT } from '../core/paths.js';
import { parseProxy } from '../core/config.js';
import { throwIfAborted, closeWithTimeout } from '../core/cancel.js';
import { redact } from '../core/redact.js';
export { parseProxy };
export function cloneProfileForWorker(sourceDir, workerId) {
  const targetDir = path.join(path.dirname(sourceDir), `.worker_${workerId}_${process.pid}_${Math.random().toString(36).slice(2, 8)}`);
  fs.mkdirSync(targetDir, { recursive: true });
  fs.cpSync(sourceDir, targetDir, {
    recursive: true,
    filter: (src) => !/Singleton|lock|\.sock$/i.test(path.basename(src)),
  });
  return targetDir;
}
export function cleanupWorkerProfile(dir) {
  if (dir && fs.existsSync(dir) && path.basename(dir).startsWith('.worker_')) {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch {}
  }
}
export function getProfileDir(projectRoot=PROJECT_ROOT, profileName='default') {return path.join(projectRoot,'data','profiles',String(profileName).replace(/[^a-zA-Z0-9_-]/g,'_')||'default');}
export function hasSavedProfile(projectRoot=PROJECT_ROOT, profileName='default') {const dir=getProfileDir(projectRoot,profileName);return fs.existsSync(dir)&&fs.readdirSync(dir).length>0;}
export const BROWSER_INSTALL_COMMAND='node node_modules/rebrowser-playwright/cli.js install chromium';
export async function launchWithFallback(engine=chromium,profileDir=null,config={},deps={}) {
  if(profileDir)fs.mkdirSync(profileDir,{recursive:true});
  const options={...REVIEW_LAUNCH_SECURITY,headless:config.headless===true,locale:config.language??'en',viewport:{width:1400,height:960},proxy:config.proxyConfig??parseProxy(config.proxy),args:[`--lang=${config.language??'en'}`,'--no-first-run']};
  const launch=opts=>profileDir?engine.launchPersistentContext(profileDir,opts):engine.launch(opts);
  try{return {resource:await launch({...options,channel:'chrome'}),channel:'chrome'};}
  catch(error){
    error.message=redact(error.message,[options.proxy?.username,options.proxy?.password]);
    if(/SingletonLock|profile.*(in use|locked)|ProcessSingleton/i.test(error.message))throw new Error('Profile is in use. Close its other browser window before retrying.');
    if(!/not found|doesn.t exist|does not exist|not installed|ENOENT|distribution|Unsupported.*channel/i.test(error.message))throw error;
    if(!(deps.existsSync??fs.existsSync)(engine.executablePath()))throw new Error(`Bundled Chromium is missing. Install with: ${BROWSER_INSTALL_COMMAND}`);
    console.warn('Installed Chrome unavailable; trying bundled Chromium.');
    return {resource:await launch(options),channel:'chromium'};
  }
}
// Only boolean signals leave the page; account labels, cookies, and credentials are never returned.
export function authSignalsInPage() {
  const account=document.querySelector('a[aria-label*="Google Account" i],button[aria-label*="Google Account" i],a[aria-label*="Google-Konto" i],button[aria-label*="Google-Konto" i],a[href*="SignOutOptions"]');
  const signin=document.querySelector('a[href*="accounts.google.com/ServiceLogin"],a[href*="accounts.google.com/signin"],a[href*="accounts.google.com/v3/signin"]');
  const text=(document.body?.innerText??document.body?.textContent??'').slice(0,4000);
  return {authState:account?'signed-in':signin?'anonymous':'unknown',insecureBrowser:/browser.*(?:not be secure|isn.t secure)|Browser.*nicht sicher/i.test(text)};
}
export async function detectAuthState(context,{signal,language='en',region='us'}={}) {
  throwIfAborted(signal);const page=await context.newPage();
  const abort=()=>{page.close().catch(()=>{});};signal?.addEventListener('abort',abort,{once:true});
  try{
    await page.goto(`https://www.google.com/maps?hl=${encodeURIComponent(language)}&gl=${encodeURIComponent(region)}`,{waitUntil:'domcontentloaded',timeout:30000});
    await page.waitForFunction(()=>document.querySelector('a[aria-label*="Google Account" i],a[aria-label*="Google-Konto" i],a[href*="accounts.google.com"]'),{timeout:5000}).catch(()=>{});
    const signals=await page.evaluate(authSignalsInPage);
    if(signals.insecureBrowser)console.warn('Google refused this browser. Try signing in manually with the installed Chrome profile; no workaround is applied.');
    return signals.authState;
  }catch(error){throwIfAborted(signal);console.warn(`Authentication probe could not be verified: ${redact(error.message)}`);return 'unknown';}
  finally{signal?.removeEventListener('abort',abort);await page.close().catch(()=>{});}
}
export async function openLogin({login=true,projectRoot=PROJECT_ROOT,profileName='default',language='en',region='us',proxy,proxyConfig}={}) {
  const dir=getProfileDir(projectRoot,profileName);
  let {resource:context}=await launchWithFallback(chromium,dir,{headless:false,language,proxy,proxyConfig});
  let didClose=false;
  const page=context.pages()[0]??await context.newPage();
  console.log(login?'Sign in to Google Maps in the opened window. Press Enter here or close that window when finished.':'Sign out in the opened window. Press Enter here or close it when finished.');
  try {
    const continueUrl = encodeURIComponent(`https://www.google.com/maps?hl=${language}&gl=${region}`);
    const loginUrl = `https://accounts.google.com/ServiceLogin?continue=${continueUrl}&hl=${encodeURIComponent(language)}`;
    await page.goto(login ? loginUrl : `https://www.google.com/maps?hl=${encodeURIComponent(language)}&gl=${encodeURIComponent(region)}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    let onInput,onClose;
    const refusalPoll=setInterval(async()=>{try{if((await page.evaluate(authSignalsInPage)).insecureBrowser)console.warn('Google says this browser may not be secure. Use normal manual sign-in if available; no bypass is attempted.');}catch{}},5000);
    try{await new Promise(resolve=>{onInput=()=>resolve();onClose=()=>{didClose=true;resolve();};context.once('close',onClose);process.stdin.once('data',onInput);process.stdin.resume();});}
    finally{clearInterval(refusalPoll);process.stdin.off('data',onInput);process.stdin.pause();context.off('close',onClose);}
    if(didClose)({resource:context}=await launchWithFallback(chromium,dir,{headless:false,language,proxy,proxyConfig}));
    const state=await detectAuthState(context,{language,region});console.log(`Profile authentication: ${state}`);return state;
  } finally {await closeWithTimeout(()=>context.close());}
}
