import fs from 'node:fs';

export class UsageError extends Error {
  constructor(message) { super(message); this.name = 'UsageError'; this.exitCode = 64; }
}
export const RUN_DEFAULTS = Object.freeze({
  sort: 'newest', language: 'en', region: 'us', concurrency: 1,
  headless: false, incremental: false, incrementalDays: 7,
  minCompleteness: 0.9, placeTimeoutMin: 60, stallTimeoutSec: 90,
  delayMs: [3000, 8000], requireLogin: false, unsafeConcurrency: false,
  profilePool: false,
});
export function positiveNumber(value, name, { integer = false, min = Number.MIN_VALUE, max = Infinity } = {}) {
  if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') throw new UsageError(`${name} must be a number`);
  const n = Number(value);
  if (!Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) throw new UsageError(`${name} must be ${integer ? 'an integer' : 'a number'} between ${min} and ${max}`);
  return n;
}
export function parseProxy(value) {
  if (value == null || value === '') return undefined;
  if (typeof value !== 'string') throw new UsageError('proxy must be a URL');
  let u;
  try { u = new URL(value); } catch { throw new UsageError('proxy must be an http, https, or socks5 URL'); }
  if (!['http:', 'https:', 'socks5:'].includes(u.protocol) || !u.hostname || (u.pathname && u.pathname !== '/') || u.search || u.hash) throw new UsageError('proxy must be an http, https, or socks5 URL without a path');
  try { return { server: `${u.protocol}//${u.host}`, ...(u.username ? { username: decodeURIComponent(u.username) } : {}), ...(u.password ? { password: decodeURIComponent(u.password) } : {}) }; }
  catch { throw new UsageError('proxy credentials contain invalid URL encoding'); }
}
export function loadProxyFile(filePath) {
  if (!filePath) return null;
  if (!fs.existsSync(filePath)) throw new UsageError(`proxy file not found: ${filePath}`);
  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#'));
  if (!lines.length) throw new UsageError(`proxy file is empty: ${filePath}`);
  return lines.map(line => parseProxy(line));
}
export function validateListingUrl(value) {
  try {
    const u = new URL(value);
    if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password) return false;
    if (u.hostname === 'maps.app.goo.gl') return u.pathname.length > 1;
    return (u.hostname === 'google.com' || u.hostname.endsWith('.google.com')) && /^\/maps\/(place|search)\//.test(u.pathname);
  } catch { return false; }
}
export function parseRunOptions(opts = {}) {
  const config = { ...RUN_DEFAULTS, ...Object.fromEntries(Object.entries(opts).filter(([, v]) => v !== undefined)) };
  if (config.limit !== undefined) config.limit = positiveNumber(config.limit, 'limit', { integer: true, min: 1 });
  config.concurrency = positiveNumber(config.concurrency, 'concurrency', { integer: true, min: 1, max: 4 });
  const aliases = { highest_rating: 'highest', lowest_rating: 'lowest', 'most-relevant': 'relevant' };
  config.sort = aliases[config.sort] ?? config.sort;
  if (!['newest', 'relevant', 'highest', 'lowest', 'default'].includes(config.sort)) throw new UsageError('sort must be newest|relevant|highest|lowest|default');
  if (!/^[a-z]{2}(-[A-Z]{2})?$/.test(config.language)) throw new UsageError('language must look like en, de, or en-US');
  if (!/^[a-z]{2}$/.test(config.region)) throw new UsageError('region must be two lowercase letters');
  if (config.profile === 'false') config.profile = false;
  if (config.profile != null && config.profile !== false && (typeof config.profile !== 'string' || !/^[A-Za-z0-9_-]+$/.test(config.profile))) throw new UsageError('profile must contain only letters, digits, underscores, or hyphens');
  config.proxyConfig = parseProxy(config.proxy);
  if (config.proxyFile) config.proxyPool = loadProxyFile(config.proxyFile);
  config.profilePool = Boolean(config.profilePool);
  config.incrementalDays = positiveNumber(config.incrementalDays, 'incremental-days');
  config.placeTimeoutMin = positiveNumber(config.placeTimeoutMin, 'place-timeout-min');
  config.stallTimeoutSec = positiveNumber(config.stallTimeoutSec, 'stall-timeout-sec');
  config.minCompleteness = positiveNumber(config.minCompleteness, 'min-completeness', { min: 0, max: 1 });
  const delay = Array.isArray(config.delayMs) ? config.delayMs : String(config.delayMs).split(',');
  if (delay.length !== 2) throw new UsageError('delay-ms must be min,max');
  config.delayMs = delay.map(v => positiveNumber(v, 'delay-ms', { integer: true, min: 0 }));
  if (config.delayMs[0] > config.delayMs[1]) throw new UsageError('delay-ms minimum must not exceed maximum');
  return config;
}
