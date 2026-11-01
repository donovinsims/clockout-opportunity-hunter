// Read authentication without relaunching Chrome or navigating an owner-owned tab.
import { authSignalsInPage } from '../vendor/reviews/src/collector/browser.js';
const mapsUrl=url=>/^https:\/\/(?:www\.)?google\.com\/maps(?:[/?#]|$)/.test(url);
export async function checkReviewAuth(context){
  const existing=context.pages().filter(p=>mapsUrl(p.url()));
  const pages=existing.length?existing:[await context.newPage()];
  const owned=!existing.length;
  let observed='unknown';
  try{
    if(owned)await pages[0].goto('https://www.google.com/maps?hl=en&gl=us',{waitUntil:'domcontentloaded',timeout:15000});
    for(const page of pages){
      await page.waitForFunction(()=>document.querySelector('[aria-label*="Google Account" i]'),null,{timeout:8000}).catch(()=>{});
      const signals=await page.evaluate(authSignalsInPage);
      if(signals.authState==='signed-in')return 'signed-in';
      if(signals.authState==='anonymous')observed='anonymous';
    }
    return observed;
  }finally{if(owned)await pages[0].close().catch(()=>{});}
}
