// Inclusive UTC windows express the uncertainty of public relative-date labels.
const UNIT_MS = { minute: 60000, hour: 3600000, day: 86400000, week: 604800000 };
const EN_MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
export const DE_MONTHS = ['Januar','Februar','März','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'];
const fold = s => s.normalize('NFD').replace(/\p{M}/gu,'').toLowerCase();
function monthIndex(name, months = EN_MONTHS) {
  const entries = Array.isArray(months) ? months.map((n,i)=>[n,i]) : Object.entries(months);
  return entries.find(([n])=>fold(n).slice(0,3)===fold(name).slice(0,3))?.[1] ?? -1;
}
function validDate(y,m,d) { if(y<100||m<0||m>11||d<1)return false;const dt=new Date(Date.UTC(y,m,d));return dt.getUTCFullYear()===y&&dt.getUTCMonth()===m&&dt.getUTCDate()===d; }
function subtract(now,n,unit) {
  if(UNIT_MS[unit])return now-n*UNIT_MS[unit];
  const dt=new Date(now),day=dt.getUTCDate();dt.setUTCDate(1);
  if(unit==='month')dt.setUTCMonth(dt.getUTCMonth()-n);else dt.setUTCFullYear(dt.getUTCFullYear()-n);
  const maxDay=new Date(Date.UTC(dt.getUTCFullYear(),dt.getUTCMonth()+1,0)).getUTCDate();dt.setUTCDate(Math.min(day,maxDay));return dt.getTime();
}
function window(earliest,latest,precision,relative,edited) {
  if(!Number.isFinite(earliest)||!Number.isFinite(latest)||earliest>latest)return null;
  try{return {earliest:new Date(earliest).toISOString(),latest:new Date(latest).toISOString(),estimate:new Date((earliest+latest)/2).toISOString(),precision,relative,edited};}catch{return null;}
}
export function prsToDate(raw, nowMs = null, months = null) {
  if(raw==null)return null;
  const now=nowMs??Date.now();if(!Number.isFinite(now))return null;
  const numeric = typeof raw==='number' || /^\d{10,16}$/.test(String(raw).trim());
  if(numeric){let n=Number(raw);if(!Number.isFinite(n))return null;n=n>1e14?Math.floor(n/1000):n<1e11?n*1000:n;return window(n,n,'minute',false,false);}
  let s=String(raw).trim().replace(/\u00a0/g,' ');const edited=/^(edited|bearbeitet)\b/i.test(s);s=s.replace(/^(edited|bearbeitet)\s*:?\s*/i,'').toLowerCase();
  if(!s)return null;
  let match=/^(a|an|\d+)\s+(min(?:ute)?s?|hrs?|hours?|days?|weeks?|months?|years?)\s+ago$/.exec(s);
  if(!match){const de=/^vor\s+(\d+|einem|einer)\s+(minuten?|stunden?|tage?n?|wochen?|monate?n?|jahre?n?)$/.exec(s);if(de){const name=de[2];match=[de[0],/^ein/.test(de[1])?'1':de[1],name.startsWith('min')?'minute':name.startsWith('stund')?'hour':name.startsWith('tag')?'day':name.startsWith('woch')?'week':name.startsWith('monat')?'month':'year'];}}
  if(match){const n=/^(a|an)$/.test(match[1])?1:Number(match[1]);if(!Number.isSafeInteger(n)||n<1)return null;const stem=match[2];const unit=stem.startsWith('min')?'minute':/^(hr|hour)/.test(stem)?'hour':stem.startsWith('day')?'day':stem.startsWith('week')?'week':stem.startsWith('month')?'month':'year';return window(subtract(now,n+1,unit),subtract(now,n,unit),unit,true,edited);}
  const iso=/^(\d{4})-(\d{2})-(\d{2})(T.*)?$/.exec(s);
  if(iso){const y=+iso[1],m=+iso[2]-1,d=+iso[3];if(!validDate(y,m,d))return null;
    if(iso[4]){if(!/^t\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:z|[+-]\d{2}:\d{2})$/.test(iso[4]))return null;const n=Date.parse(s);return window(n,n,'minute',false,edited);}
    const start=Date.UTC(y,m,d);return window(start,start+86400000-1,'day',false,edited);
  }
  const isoMonth=/^(\d{4})-(\d{2})$/.exec(s);
  let y,m,d;
  if(isoMonth){y=+isoMonth[1];m=+isoMonth[2]-1;}
  else {
    const en=/^([\p{L}]+)\.?\s+(\d{1,2}),?\s+(\d{4})$/u.exec(s);
    const de=/^(\d{1,2})\.?\s+([\p{L}]+)\.?\s+(\d{4})$/u.exec(s);
    const mo=/^([\p{L}]+)\.?\s+(\d{4})$/u.exec(s);
    if(en){m=monthIndex(en[1],months??EN_MONTHS);d=+en[2];y=+en[3];}
    else if(de){m=monthIndex(de[2],months??DE_MONTHS);d=+de[1];y=+de[3];}
    else if(mo){m=monthIndex(mo[1],months??EN_MONTHS);y=+mo[2];}else return null;
  }
  if(!validDate(y,m,d??1))return null;
  const start=Date.UTC(y,m,d??1),end=d==null?Date.UTC(y,m+1,1)-1:start+86400000-1;
  return window(start,end,d==null?'month':'day',false,edited);
}
