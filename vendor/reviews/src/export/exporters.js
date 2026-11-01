import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
export const EXPORT_SCHEMA_VERSION = 2;
export const EXPORT_COLUMNS = Object.freeze(['placeId','reviewId','reviewerName','reviewerProfileUrl','rating','ratingRaw','reviewText','originalLanguage','translatedByGoogle','publishedDateRaw','publishedDateParsed','publishedDateEarliest','publishedDateLatest','datePrecision','isEdited','ownerResponse','ownerResponseDateRaw','ownerResponseDateParsed','ownerResponseDateEarliest','ownerResponseDateLatest','ownerResponseDatePrecision','ownerResponseIsEdited','textTruncated','feedRank','reviewUrl','firstCollectedAt','lastCollectedAt','collectedCount','runId']);
const booleans = new Set(['translatedByGoogle','isEdited','ownerResponseIsEdited','textTruncated']);
function csvCell(value, raw) {
  if(value==null)return '';
  let s=String(value);if(!raw&&typeof value==='string'&&/^[=+\-@\t\r]/.test(value))s="'"+s;
  return /[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;
}
export function toCsv(rows, headers=EXPORT_COLUMNS, {bom=false,raw=false}={}){
  const lines=[headers.map(h=>csvCell(h,true)).join(',')];
  for(const row of rows)lines.push(headers.map(h=>{let value=row[h];if(booleans.has(h)&&value!=null)value=!!value;return csvCell(value,raw);}).join(','));
  return (bom?'\uFEFF':'')+lines.join('\r\n')+'\r\n';
}
export function toJsonExport(rows,meta={}){return JSON.stringify({...meta,schemaVersion:2,columns:EXPORT_COLUMNS,exportedAt:new Date().toISOString(),reviews:rows},null,2)+'\n';}
export function writeExport(filename,body){const dest=path.resolve(filename);fs.mkdirSync(path.dirname(dest),{recursive:true});const tmp=dest+'.'+randomUUID()+'.tmp';try{fs.writeFileSync(tmp,body,{flag:'wx'});fs.renameSync(tmp,dest);}finally{fs.rmSync(tmp,{force:true});}}
