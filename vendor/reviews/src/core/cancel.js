import { setTimeout } from 'node:timers/promises';
export function throwIfAborted(signal) { if (signal?.aborted) throw signal.reason ?? new DOMException('Interrupted', 'AbortError'); }
export function sleep(ms, signal) { return setTimeout(ms, undefined, signal ? { signal } : undefined); }
export function isAbort(error, signal) { return !!signal?.aborted || error?.name === 'AbortError'; }
export async function closeWithTimeout(close, timeoutMs = 10000) {
  let timer;
  try { return await Promise.race([Promise.resolve().then(close), new Promise((_, reject) => { timer = setTimeoutNative(() => reject(new Error(`Browser cleanup exceeded ${timeoutMs}ms`)), timeoutMs); })]); }
  finally { clearTimeout(timer); }
}
const setTimeoutNative = globalThis.setTimeout;
