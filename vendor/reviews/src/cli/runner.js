import { randomUUID } from 'node:crypto';
import { DEFAULT_DB } from '../core/paths.js';
import { createStore } from '../core/store.js';
import { normalizeReview } from '../core/normalize.js';
import { parseRunOptions, validateListingUrl, UsageError } from '../core/config.js';
import { aggregateJob, itemStatusFor } from '../core/termination.js';
import { redact } from '../core/redact.js';

export async function collectForPlaces(input, deps = {}) {
  const now = deps.now ?? Date.now;
  const initial = parseRunOptions(input);
  const sanitize = value => redact(value, [initial.proxyConfig?.username, initial.proxyConfig?.password]);
  const store = (deps.createStore ?? createStore)(input.db ?? DEFAULT_DB, { now });
  const controller = new AbortController();
  let signals = 0, jobId = input.resume ?? input.jobId ?? `job-${randomUUID()}`;
  let config, created = false, writeQueue = Promise.resolve();
  const states = new Map();
  const stateFor = idx => { if (!states.has(idx)) states.set(idx, { seen: new Set(), collected: 0, started: now(), error: null, conflicts: [] }); return states.get(idx); };
  const onSignal = signal => {
    if (++signals > 1) process.exit(130);
    console.error(`Interrupted (${signal}); saving progress and closing browser...`);
    controller.abort(new DOMException(`Interrupted by ${signal}`, 'AbortError'));
  };
  const externalAbort = () => controller.abort(input.signal.reason);
  if (input.signal?.aborted) externalAbort(); else input.signal?.addEventListener('abort', externalAbort, { once: true });
  process.on('SIGINT', onSignal); process.on('SIGTERM', onSignal);
  const summarize = item => ({
    listingUrl: item.inputUrl, idx: item.idx, placeId: item.placeId ?? null,
    placeName: item.termination?.placeName ?? null, status: item.status,
    collected: item.collectedCount ?? 0, expected: item.expectedCount ?? null,
    completeness: item.completeness ?? null, termination: item.termination ?? null,
    error: item.error ?? null, attempts: item.attempt ?? 0, durationMs: item.termination?.durationMs ?? 0,
  });
  try {
    let saved = {};
    if (input.resume) {
      const existing = store.getJob(input.resume);
      if (!existing) throw new UsageError(`Cannot resume: job "${input.resume}" not found`);
      saved = { ...existing.config };
      if (saved.proxy && !input.proxy) throw new UsageError('Resume requires --proxy to be supplied again; stored credentials are redacted');
      delete saved.proxy; delete saved.proxyConfig;
      if (input.listingUrls && JSON.stringify(input.listingUrls) !== JSON.stringify(saved.listingUrls)) throw new UsageError('Resume restores the original URL list; omit URLs');
      // Older jobs may lack pre-created rows. Backfill by original index, never URL membership.
      for (const [idx, inputUrl] of (saved.listingUrls ?? []).entries()) if (!existing.items.some(i => i.idx === idx)) store.recordJobItem({ jobId, idx, inputUrl, status: 'pending' });
      created = true;
    }
    config = parseRunOptions({ ...saved, ...input });
    config.listingUrls ??= [];
    if (!created) { store.createJob({ id: jobId, config, totalPlaces: config.listingUrls.length }); created = true; }
    else { store.updateJobConfig(jobId, config); store.updateJobStatus(jobId, 'running', 'Resuming unfinished items'); }

    const onBatch = (data, listingUrl, idx) => {
      const state = stateFor(idx);
      const operation = writeQueue.then(() => {
        if (state.error) throw state.error;
        if (!data.place?.placeId || !data.reviews?.length) return;
        const fresh = data.reviews.filter(r => r.reviewId && !state.seen.has(r.reviewId));
        const unique = [...new Map(fresh.map(r => [r.reviewId, r])).values()].slice(0, config.limit == null ? undefined : Math.max(0, config.limit - state.collected));
        if (!unique.length) return;
        const placeId = data.place.placeId;
        store.upsertBusinessMeta({ ...data.place, placeId, listingUrl: data.place.url ?? listingUrl, inputUrl: listingUrl });
        const normalized = unique.map(r => normalizeReview(r, { placeId, listingUrl, runId: jobId, now: now() }).record);
        store.upsertReviews(normalized, jobId, { onConflict: conflict => state.conflicts.push(conflict) });
        for (const r of unique) state.seen.add(r.reviewId);
        state.collected += unique.length;
      }).catch(error => { state.error = error; throw error; });
      // The returned operation rejects to the collector; the tail only keeps the queue drainable.
      writeQueue = operation.catch(() => {});
      return operation;
    };
    const onComplete = async (result, listingUrl, idx, attempts = 1) => {
      await writeQueue;
      const state = stateFor(idx), place = result.place ?? {};
      let termination = { ...result.termination };
      if (state.error) termination = { ...termination, reason: 'persistence-error', detail: state.error.message };
      let status = itemStatusFor(termination.reason, { collected: state.collected });
      const expected = Number.isFinite(place.reviewsCount) ? place.reviewsCount : null;
      const completeness = expected > 0 ? Math.min(1, state.collected / expected) : expected === 0 && termination.reason === 'no-reviews' ? 1 : null;
      if (status === 'done' && termination.reason !== 'limit-reached' && completeness != null && completeness < config.minCompleteness) { termination.reason = 'incomplete'; status = 'partial'; }
      if (status === 'done' && result.reviews?.some(r => r.textTruncated)) { termination.reason = 'incomplete'; termination.detail = 'One or more review texts remain truncated'; status = 'partial'; }
      if (place.placeId) store.upsertBusinessMeta({ ...place, listingUrl: place.url ?? listingUrl, inputUrl: listingUrl });
      const durationMs = result.durationMs ?? termination.durationMs ?? Math.max(0, now() - state.started);
      termination = sanitize({ ...termination, authState: termination.authState ?? config.authState ?? 'unknown', placeName: place.name ?? null, durationMs });
      store.recordJobItem({ jobId, idx, inputUrl: listingUrl, placeId: place.placeId ?? null, status, attempt: attempts, error: sanitize(state.error?.message ?? result.error ?? (status === 'failed' ? termination.detail : null)), termination,
        diagnostics: sanitize({ ...result.diagnostics, dateConflicts: state.conflicts }), expectedCount: expected, collectedCount: state.collected, completeness });
      if (place.placeId && status === 'done' && (completeness >= config.minCompleteness && completeness !== null || (termination.reason === 'no-more-reviews' && termination.endMarkerSeen))) store.markCompleted(place.placeId);
      return summarize(store.getJob(jobId).items.find(i => i.idx === idx));
    };
    let pending = store.getJob(jobId).items.filter(i => !['done','skipped'].includes(i.status));
    for (const item of pending) if (!validateListingUrl(item.inputUrl)) await onComplete({ termination: { reason: 'invalid-url', detail: 'Not a recognized HTTP(S) Google Maps place/search URL' } }, item.inputUrl, item.idx, 0);
    pending = pending.filter(i => validateListingUrl(i.inputUrl));
    if (pending.length && !controller.signal.aborted) {
      const { launchBatchCollector } = deps.launchBatchCollector ? deps : await import('../collector/batch.js');
      const returned = await launchBatchCollector(pending.map(i => ({ url: i.inputUrl, idx: i.idx })), {
        ...config, jobId, signal: controller.signal,
        isPlaceCollected: id => store.isPlaceCollected(id, config.incrementalDays),
        onAuthState: authState => { config.authState = authState; store.updateJobConfig(jobId, config); },
      }, onComplete, onBatch);
      // A callback can fail before its checkpoint is stored. Reconcile explicit collector failures.
      for (const item of returned ?? []) {
        const previous = store.getJob(jobId).items.find(i => i.idx === item.idx);
        if (item.status === 'failed' && previous && previous.status !== 'failed') {
          store.recordJobItem({ jobId, idx: previous.idx, inputUrl: previous.inputUrl,
            placeId: item.placeId, status: 'failed', attempt: item.attempts ?? previous.attempt,
            error: item.error, termination: item.termination ?? { reason: 'failed' },
            expectedCount: item.expected ?? previous.expectedCount,
            collectedCount: stateFor(previous.idx).collected });
        }
      }
    }
    await writeQueue;
    const items = store.getJob(jobId).items;
    const outcome = aggregateJob(items, { interrupted: controller.signal.aborted });
    store.updateJobStatus(jobId, outcome.status, `Finished: ${JSON.stringify(store.getJob(jobId).counts)}`);
    const summary = items.map(summarize);
    console.table(summary.map(i => ({ URL: i.listingUrl, status: i.status, reviews: `${i.collected}/${i.expected ?? '?'}`, reason: i.termination?.reason ?? 'pending' })));
    console.log(`Job ${jobId}: ${outcome.status}`);
    return { jobId, ...outcome, summary };
  } catch (error) {
    if (created) store.updateJobStatus(jobId, controller.signal.aborted ? 'interrupted' : 'failed', sanitize(error.message));
    if (controller.signal.aborted) return { jobId, status: 'interrupted', exitCode: 130, summary: (store.getJob(jobId)?.items ?? []).map(summarize) };
    error.message = sanitize(error.message); throw error;
  } finally {
    await writeQueue;
    process.off('SIGINT', onSignal); process.off('SIGTERM', onSignal);
    input.signal?.removeEventListener('abort', externalAbort);
    store.close();
  }
}
