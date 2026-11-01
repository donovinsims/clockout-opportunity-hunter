const definitions = {
  done: ['limit-reached', 'no-more-reviews', 'no-reviews'],
  skipped: ['skipped-incremental'],
  partial: ['incomplete', 'anonymous-preview-limit', 'pagination-stall', 'timeout', 'sign-in-required', 'structure-drift', 'interrupted'],
  blocked: ['blocked', 'captcha', 'sign-in-wall', 'consent-wall'],
  failed: ['missing-place-id', 'search-mismatch', 'structure-unknown', 'invalid-url', 'sort-failed', 'persistence-error', 'failed'],
};
export const TERMINATIONS = Object.freeze(Object.fromEntries(Object.entries(definitions).flatMap(([status,reasons]) => reasons.map(reason => [reason, Object.freeze({ status, retryable: false })]))));
export function itemStatusFor(reason, { collected = 0 } = {}) {
  if (!TERMINATIONS[reason]) throw new Error(`Unknown termination reason: ${reason}`);
  return reason === 'structure-drift' && !collected ? 'failed' : TERMINATIONS[reason].status;
}
export function aggregateJob(items, { interrupted = false } = {}) {
  if (interrupted) return { status: 'interrupted', exitCode: 130 };
  if (!items.length || items.every(i => i.status === 'pending') || items.some(i => i.status === 'failed')) return { status: 'failed', exitCode: 1 };
  if (items.some(i => i.status === 'blocked')) return { status: 'blocked', exitCode: 3 };
  if (items.some(i => !['done', 'skipped'].includes(i.status))) return { status: 'partial', exitCode: 2 };
  return { status: 'completed', exitCode: 0 };
}
export function decideTermination(s) {
  if (s.aborted) return 'interrupted';
  if (s.noReviewsDetected) return 'no-reviews';
  if (s.limit && s.collected >= s.limit) return 'limit-reached';
  if (s.endMarkerSeen && !s.collected) return 'structure-unknown';
  if (s.endMarkerSeen || (s.expected > 0 && s.collected >= .98 * s.expected)) {
    return s.expected > 0 && s.collected / s.expected < (s.minCompleteness ?? .9) ? 'incomplete' : 'no-more-reviews';
  }
  if (s.hardTimeoutMs != null && s.elapsedMs >= s.hardTimeoutMs) return 'timeout';
  if (s.stalled && s.recoveryDone && !s.spinnerVisible && s.stalledForMs >= (s.stallTimeoutMs ?? 90000)) {
    // The feed was scrolled to its physical bottom for the full stall window with no new
    // content and no spinner: pagination has ended. Use the same completeness rule as the
    // end marker so short listings report complete instead of stalled.
    if (s.feedAtEnd && s.collected > 0) {
      return s.expected > 0 && s.collected / s.expected < (s.minCompleteness ?? .9) ? 'incomplete' : 'no-more-reviews';
    }
    return s.authState === 'anonymous' && s.expected > s.collected ? 'anonymous-preview-limit' : 'pagination-stall';
  }
  return 'continue';
}
