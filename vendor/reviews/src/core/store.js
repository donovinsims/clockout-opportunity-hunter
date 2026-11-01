import { openDb } from './db.js';
import { DEFAULT_DB } from './paths.js';
import { redact } from './redact.js';

const REVIEW_FIELDS = ['reviewId','placeId','reviewerName','reviewerProfileUrl','rating','ratingRaw','reviewText','originalLanguage','translatedByGoogle','publishedDateRaw','publishedDateParsed','publishedDateEarliest','publishedDateLatest','datePrecision','isEdited','ownerResponse','ownerResponseDateRaw','ownerResponseDateParsed','ownerResponseDateEarliest','ownerResponseDateLatest','ownerResponseDatePrecision','ownerResponseIsEdited','textTruncated','feedRank','reviewUrl','firstCollectedAt','lastCollectedAt','collectedCount','runId'];
const countsFor = items => Object.fromEntries(['pending','running','done','skipped','partial','blocked','failed'].map(status => [status,items.filter(i => i.status === status).length]));
const json = v => v == null ? null : JSON.stringify(redact(v));
function parseItem(row) { return { ...row, termination: row.termination ? JSON.parse(row.termination) : null, diagnostics: row.diagnostics ? JSON.parse(row.diagnostics) : null }; }

export function createStore(dbPath = DEFAULT_DB, { now = () => Date.now() } = {}) {
  const db = openDb(dbPath); let closed = false;
  const timestamp = () => new Date(now()).toISOString();
  function transaction(fn) { db.exec('BEGIN IMMEDIATE'); try { const v=fn();db.exec('COMMIT');return v; } catch(e){db.exec('ROLLBACK');throw e;} }
  function upsertBusinessMeta(meta) {
    if (!meta?.placeId) return;
    if (!meta.listingUrl) throw new Error('listingUrl is required for business metadata');
    db.prepare(`INSERT INTO businesses(placeId,name,listingUrl,inputUrl,reviewsCount,rating,firstSeenAt,lastSeenAt) VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(placeId) DO UPDATE SET name=COALESCE(excluded.name,name),listingUrl=excluded.listingUrl,inputUrl=COALESCE(excluded.inputUrl,inputUrl),reviewsCount=COALESCE(excluded.reviewsCount,reviewsCount),rating=COALESCE(excluded.rating,rating),lastSeenAt=excluded.lastSeenAt`)
      .run(meta.placeId,meta.name??null,meta.listingUrl,meta.inputUrl??null,meta.reviewsCount??null,meta.rating??null,timestamp(),timestamp());
  }
  function upsertReview(rec, runId) {
    if (!rec?.placeId || !rec.reviewId) throw new Error('placeId and reviewId are required');
    const old = db.prepare('SELECT * FROM reviews WHERE placeId=? AND reviewId=?').get(rec.placeId,rec.reviewId);
    const merged = { ...old }; const conflicts = [];
    for (const field of REVIEW_FIELDS) if (rec[field] != null) merged[field] = typeof rec[field] === 'boolean' ? Number(rec[field]) : rec[field];
    // A complete prior body must survive a partial observation, but complete edits can shorten it.
    if (old?.reviewText != null && (!rec.reviewText || rec.textTruncated)) { merged.reviewText=old.reviewText;merged.textTruncated=old.textTruncated; }
    for (const prefix of ['publishedDate','ownerResponseDate']) {
      const lo=rec[prefix+'Earliest'],hi=rec[prefix+'Latest'];
      if (!lo || !hi) continue;
      let earliest=lo,latest=hi;
      if (old?.[prefix+'Earliest'] && old?.[prefix+'Latest']) {
        earliest=lo>old[prefix+'Earliest']?lo:old[prefix+'Earliest'];latest=hi<old[prefix+'Latest']?hi:old[prefix+'Latest'];
        if(earliest>latest){ earliest=lo;latest=hi;conflicts.push(prefix); }
      }
      merged[prefix+'Earliest']=earliest;merged[prefix+'Latest']=latest;
      merged[prefix+'Parsed']=new Date((Date.parse(earliest)+Date.parse(latest))/2).toISOString();
    }
    merged.firstCollectedAt=old?.firstCollectedAt??timestamp();merged.lastCollectedAt=timestamp();
    merged.collectedCount=old?old.collectedCount+Number((old.runId??null)!==(runId??null)):1;merged.runId=runId??null;
    const values=REVIEW_FIELDS.map(k=>merged[k]??null);
    db.prepare(`INSERT INTO reviews (${REVIEW_FIELDS.join(',')}) VALUES (${REVIEW_FIELDS.map(()=>'?').join(',')}) ON CONFLICT(placeId,reviewId) DO UPDATE SET ${REVIEW_FIELDS.filter(k=>!['placeId','reviewId'].includes(k)).map(k=>`${k}=excluded.${k}`).join(',')}`).run(...values);
    return { conflicts };
  }
  function upsertReviews(records, runId, { onConflict = () => {} } = {}) {
    if(!records?.length)return 0;
    return transaction(()=>{const conflicts=[];for(const r of records){const out=upsertReview(r,runId);for(const field of out.conflicts)conflicts.push({reviewId:r.reviewId,field});}for(const conflict of conflicts)onConflict(conflict);return records.length;});
  }
  function countReviews(placeId) { return (placeId?db.prepare('SELECT COUNT(*) AS n FROM reviews WHERE placeId=?').get(placeId):db.prepare('SELECT COUNT(*) AS n FROM reviews').get()).n; }
  function selectReviews({placeId,limit,offset=0}={}) {
    let sql='SELECT * FROM reviews';const args=[];if(placeId){sql+=' WHERE placeId=?';args.push(placeId);}sql+=' ORDER BY placeId, publishedDateParsed DESC, reviewId';
    if(limit!=null){sql+=' LIMIT ? OFFSET ?';args.push(limit,offset);}return db.prepare(sql).all(...args);
  }
  function selectPlaces(){return db.prepare('SELECT * FROM businesses ORDER BY firstSeenAt DESC,placeId').all();}
  function deleteReviews(placeId){return transaction(()=>{db.prepare('DELETE FROM job_items WHERE placeId=?').run(placeId);db.prepare('DELETE FROM reviews WHERE placeId=?').run(placeId);db.prepare('DELETE FROM businesses WHERE placeId=?').run(placeId);});}
  function retentionVacuum(days){db.prepare('DELETE FROM reviews WHERE lastCollectedAt < ?').run(new Date(now()-days*86400000).toISOString());db.exec('PRAGMA incremental_vacuum');return countReviews();}
  function createJob({id,config={},totalPlaces=0,notes=null}){
    transaction(()=>{db.prepare("INSERT INTO jobs(id,createdAt,updatedAt,status,config,totalPlaces,notes) VALUES(?,?,?,'running',?,?,?)").run(id,timestamp(),timestamp(),json(config),totalPlaces,redact(notes));
      for(const [idx,inputUrl] of (config.listingUrls??[]).entries())recordJobItem({jobId:id,idx,inputUrl,status:'pending',attempt:0});});
  }
  function updateJobStatus(id,status,notes=null){db.prepare('UPDATE jobs SET status=?,updatedAt=?,notes=COALESCE(?,notes) WHERE id=?').run(status,timestamp(),redact(notes),id);}
  function updateJobConfig(id,config){db.prepare('UPDATE jobs SET config=?,updatedAt=? WHERE id=?').run(json(config),timestamp(),id);}
  function recordJobItem({jobId,idx,inputUrl,placeId=null,status='pending',attempt=0,error=null,termination=null,diagnostics=null,expectedCount=null,collectedCount=null,completeness=null}){
    inputUrl=redact(inputUrl);
    const previous=db.prepare('SELECT inputUrl FROM job_items WHERE jobId=? AND idx=?').get(jobId,idx);
    if(previous&&previous.inputUrl!==inputUrl)throw new Error(`inputUrl mismatch for job ${jobId} index ${idx}`);
    db.prepare(`INSERT INTO job_items(jobId,idx,inputUrl,placeId,status,attempt,error,termination,diagnostics,expectedCount,collectedCount,completeness,updatedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(jobId,idx) DO UPDATE SET placeId=COALESCE(excluded.placeId,placeId),status=excluded.status,attempt=excluded.attempt,error=excluded.error,termination=excluded.termination,diagnostics=excluded.diagnostics,expectedCount=excluded.expectedCount,collectedCount=excluded.collectedCount,completeness=excluded.completeness,updatedAt=excluded.updatedAt`)
      .run(jobId,idx,inputUrl,placeId,status,attempt,redact(error),json(termination),json(diagnostics),expectedCount,collectedCount,completeness,timestamp());
  }
  function getJob(id){const job=db.prepare('SELECT * FROM jobs WHERE id=?').get(id);if(!job)return null;const items=db.prepare('SELECT * FROM job_items WHERE jobId=? ORDER BY idx').all(id).map(parseItem);return {...job,config:job.config?JSON.parse(job.config):{},items,counts:countsFor(items)};}
  function selectRecentJobs(limit=20){return db.prepare('SELECT id FROM jobs ORDER BY createdAt DESC,id DESC LIMIT ?').all(limit).map(j=>getJob(j.id));}
  function markCompleted(placeId,at=timestamp()){db.prepare('UPDATE businesses SET lastCompletedAt=? WHERE placeId=?').run(at,placeId);}
  function isPlaceCollected(placeId,maxAgeDays=30){const row=db.prepare('SELECT lastCompletedAt FROM businesses WHERE placeId=?').get(placeId);return !!row?.lastCompletedAt&&(maxAgeDays==null||now()-Date.parse(row.lastCompletedAt)<maxAgeDays*86400000);}
  function close(){if(!closed){db.close();closed=true;}}
  return {database:db,close,upsertBusinessMeta,upsertReview,upsertReviews,countReviews,selectReviews,selectPlaces,deleteReviews,retentionVacuum,createJob,updateJobStatus,updateJobConfig,recordJobItem,getJob,selectRecentJobs,markCompleted,isPlaceCollected};
}
