import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { chromium } from 'rebrowser-playwright';
import { DEFAULT_DB, PROJECT_ROOT } from '../core/paths.js';
import { getProfileDir, hasSavedProfile, launchWithFallback, detectAuthState } from '../collector/browser.js';
import { closeWithTimeout } from '../core/cancel.js';
import { redact } from '../core/redact.js';
export async function doctor(config={},deps={}) {
  const checks=[];const record=(name,pass,detail='')=>{checks.push({name,pass,detail});console.log(`${pass?'PASS':'FAIL'} ${name}${detail?': '+detail:''}`);};
  const [major,minor]=process.versions.node.split('.').map(Number);record('Node >=22.13',major>22||major===22&&minor>=13,process.version);
  try{const db=new DatabaseSync(':memory:');db.close();record('node:sqlite',true);}catch(error){record('node:sqlite',false,error.message);}
  const dbPath=config.db??DEFAULT_DB;
  try{if(dbPath!==':memory:'){fs.mkdirSync(path.dirname(path.resolve(dbPath)),{recursive:true});fs.accessSync(fs.existsSync(dbPath)?dbPath:path.dirname(path.resolve(dbPath)),fs.constants.W_OK);}record('Database writable',true,dbPath);}catch(error){record('Database writable',false,error.message);}
  const profile=config.profile??'default',exists=hasSavedProfile(PROJECT_ROOT,profile);record('Profile exists',exists,profile);
  let resource;
  try{
    const launched=await (deps.launchWithFallback??launchWithFallback)(deps.chromium??chromium,exists?getProfileDir(PROJECT_ROOT,profile):null,{...config,headless:true});resource=launched.resource;record('Browser executable',true,launched.channel);
  }catch(error){record('Browser executable',false,redact(error.message));}
  if(resource){
    try{
      const context=exists?resource:await resource.newContext({locale:config.language??'en'});
      try{const state=await (deps.detectAuthState??detectAuthState)(context,config);record('Signed in',state==='signed-in',state);}
      finally{if(!exists)await context.close();}
    }catch(error){record('Signed in',false,redact(error.message));}
    finally{await closeWithTimeout(()=>resource.close());}
  }else{record('Signed in',false,'Browser launch failed');}
  return {ok:checks.every(c=>c.pass),checks};
}
