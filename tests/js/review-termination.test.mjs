// Unit tests for the adapted pagination-end decision in vendor/reviews/src/core/termination.js.
// Run: node --test tests/js/review-termination.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { decideTermination } from '../../vendor/reviews/src/core/termination.js';

const base = {
  collected: 2,
  expected: null,
  limit: 5,
  authState: 'signed-in',
  endMarkerSeen: false,
  noReviewsDetected: false,
  minCompleteness: .9,
  elapsedMs: 120000,
  hardTimeoutMs: 3600000,
  stalled: true,
  recoveryDone: true,
  spinnerVisible: false,
  stalledForMs: 120000,
};

test('short listing at the feed bottom finishes as no-more-reviews instead of stalled', () => {
  assert.equal(decideTermination({ ...base, feedAtEnd: true }), 'no-more-reviews');
});

test('feed-bottom with shortfall against a known count stays incomplete, not stalled', () => {
  assert.equal(decideTermination({ ...base, feedAtEnd: true, expected: 5, collected: 2 }), 'incomplete');
});

test('feed-bottom only applies when something was collected', () => {
  assert.equal(decideTermination({ ...base, feedAtEnd: true, collected: 0 }), 'pagination-stall');
});

test('no feed-bottom keeps the previous stall classification', () => {
  assert.equal(decideTermination({ ...base, feedAtEnd: false }), 'pagination-stall');
});

test('anonymous shortfall without feed-bottom is still the anonymous preview limit', () => {
  assert.equal(
    decideTermination({ ...base, feedAtEnd: false, authState: 'anonymous', expected: 10, collected: 3 }),
    'anonymous-preview-limit',
  );
});

test('limit reached and the end marker behave exactly as before', () => {
  assert.equal(decideTermination({ ...base, feedAtEnd: true, stalled: false, collected: 5, limit: 5 }), 'limit-reached');
  assert.equal(decideTermination({ ...base, feedAtEnd: true, endMarkerSeen: true }), 'no-more-reviews');
  assert.equal(decideTermination({ ...base, endMarkerSeen: true, expected: 4, collected: 3 }), 'incomplete');
});
