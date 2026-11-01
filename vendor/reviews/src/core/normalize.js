import { prsToDate } from './dates.js';
export function normalizeRating(value) {
  if(value==null)return {rating:null,ratingRaw:null};
  if(typeof value==='number')return {rating:Number.isInteger(value)&&value>=1&&value<=5?value:null,ratingRaw:String(value)};
  const raw=String(value);const m=/^(?:rated\s+)?([1-5])(?:\.0)?\s*(?:stars?|\/\s*5|out of 5|sterne?|von 5)$/i.exec(raw.trim());
  return {rating:m?Number(m[1]):null,ratingRaw:raw};
}
export function boolOrNull(v) {return v===true||v===1?1:v===false||v===0?0:null;}
const string = v => typeof v==='string'&&v.length?v:null;
const iso = v => typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T/.test(v)&&Number.isFinite(Date.parse(v))?new Date(v).toISOString():null;
export function normalizeReview(raw={},ctx={}) {
  const r=normalizeRating(raw.ratingRaw??raw.rating),record={
    reviewId:string(raw.reviewId),placeId:string(raw.placeId)??string(ctx.placeId),
    reviewerName:string(raw.reviewerName),reviewerProfileUrl:string(raw.reviewerProfileUrl),rating:r.rating,ratingRaw:r.ratingRaw,
    reviewText:string(raw.reviewText),originalLanguage:string(raw.originalLanguage),translatedByGoogle:boolOrNull(raw.translatedByGoogle),
    publishedDateRaw:string(raw.publishedDateRaw),ownerResponse:string(raw.ownerResponse),ownerResponseDateRaw:string(raw.ownerResponseDateRaw),
    reviewUrl:string(raw.reviewUrl),textTruncated:boolOrNull(raw.textTruncated),feedRank:Number.isInteger(raw.feedRank)&&raw.feedRank>=0?raw.feedRank:null,
    ...(ctx.runId?{runId:ctx.runId}:{}),...(ctx.listingUrl?{listingUrl:ctx.listingUrl}:{}),
  };
  for(const [prefix,precision,edited] of [['publishedDate','datePrecision','isEdited'],['ownerResponseDate','ownerResponseDatePrecision','ownerResponseIsEdited']]){
    const parsed=prsToDate(raw[prefix+'Raw'],ctx.now);
    for(const [column,key] of [['Parsed','estimate'],['Earliest','earliest'],['Latest','latest']])record[prefix+column]=iso(raw[prefix+column])??parsed?.[key]??null;
    record[precision]=typeof raw[precision]==='string'?raw[precision]:parsed?.precision??null;
    record[edited]=boolOrNull(raw[edited])??(parsed?Number(parsed.edited):null);
  }
  return {record,warnings:[]};
}
