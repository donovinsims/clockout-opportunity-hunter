import { Command } from 'commander';
import fs from 'node:fs';
import path from 'node:path';
import { PROJECT_ROOT, DEFAULT_DB } from '../core/paths.js';
import { parseRunOptions, positiveNumber, UsageError } from '../core/config.js';

export function resolveUrlList(projectRoot, args = []) {
  return args.flatMap(arg => {
    if (/^https?:\/\//i.test(arg)) return [arg];
    const filename = path.resolve(projectRoot, arg);
    if (!fs.existsSync(filename) || !fs.statSync(filename).isFile()) return [arg];
    return fs.readFileSync(filename, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#'));
  });
}
function closeStore(store) { if (store.close) store.close(); else store.database.close(); }
export function buildProgram(deps = {}) {
  const program = new Command();
  program.name('gmr').description('Local Google Maps review collector').version('0.1.0').exitOverride();
  program.command('login').description('Interactively sign in to a local persistent profile')
    .option('--profile <name>', 'profile name', 'default').option('--logout', 'open Google Maps for sign-out')
    .option('--language <code>', 'UI language', 'en').option('--proxy <url>', 'proxy URL')
    .action(async opts => {
      const config = parseRunOptions(opts);
      const { openLogin } = await import('../collector/browser.js');
      await openLogin({ ...config, login: !opts.logout, projectRoot: PROJECT_ROOT, profileName: config.profile });
    });
  program.command('run').description('Collect place URLs or newline-delimited URL files')
    .argument('[urls...]', 'Google Maps URLs or files; optional with --resume')
    .option('--limit <n>', 'maximum reviews per place')
    .option('--concurrency <n>', 'parallel places (1–4; persistent profile defaults to 1)')
    .option('--sort <mode>', 'newest|relevant|highest|lowest|default')
    .option('--language <code>', 'UI language, default en').option('--region <code>', 'region, default us')
    .option('--profile <name>', 'persistent profile').option('--no-profile', 'anonymous collection')
    .option('--headless', 'run without a browser window').option('--proxy <url>', 'proxy URL')
    .option('--proxy-file <path>', 'file containing list of proxies for rotation')
    .option('--profile-pool', 'clone ephemeral profiles for safe persistent concurrency')
    .option('--incremental', 'skip recently completed places').option('--incremental-days <n>', 'freshness days, default 7')
    .option('--resume <jobId>', 'resume unfinished items using saved options')
    .option('--require-login', 'require verified signed-in state')
    .option('--unsafe-concurrency', 'allow parallel tabs in a persistent profile')
    .option('--delay-ms <min,max>', 'delay between places, default 3000,8000')
    .option('--min-completeness <n>', 'minimum completeness, default 0.9')
    .option('--place-timeout-min <n>', 'hard ceiling, default 60 minutes')
    .option('--stall-timeout-sec <n>', 'no-progress timeout, default 90 seconds')
    .option('--db <path>', 'database path')
    .action(async (args, opts, command) => {
      const explicit = Object.fromEntries(Object.entries(opts).filter(([key]) => command.getOptionValueSource(key) === 'cli'));
      parseRunOptions(explicit);
      if (!args.length && !opts.resume) throw new UsageError('run needs at least one URL or --resume <jobId>');
      const { collectForPlaces } = deps.collectForPlaces ? deps : await import('./runner.js');
      const result = await collectForPlaces({ ...explicit, ...(args.length ? { listingUrls: resolveUrlList(PROJECT_ROOT, args) } : {}) });
      process.exitCode = result.exitCode;
    });
  program.command('status').description('Show expected/collected counts and the last ten jobs')
    .option('--db <path>', 'database path').action(async opts => {
      const { createStore } = await import('../core/store.js'); const store = createStore(opts.db ?? DEFAULT_DB);
      try {
        console.table(store.selectPlaces().map(p => ({ featureId: p.placeId, name: p.name, expected: p.reviewsCount, collected: store.countReviews(p.placeId) })));
        console.table(store.selectRecentJobs(10).map(j => ({ id: j.id, status: j.status, ...(j.counts ?? {}) })));
      } finally { closeStore(store); }
    });
  program.command('export').description('Export stored reviews')
    .requiredOption('--format <format>', 'csv|json').option('--placeId <id>', 'feature ID filter')
    .option('--out <path>', 'destination file').option('--no-bom', 'omit CSV BOM')
    .option('--raw-csv', 'disable formula protection').option('--db <path>', 'database path')
    .action(async opts => {
      if (!['csv', 'json'].includes(opts.format)) throw new UsageError('format must be csv|json');
      const { createStore } = await import('../core/store.js');
      const { toCsv, toJsonExport, writeExport } = await import('../export/exporters.js');
      const store = createStore(opts.db ?? DEFAULT_DB);
      try {
        const rows = store.selectReviews({ placeId: opts.placeId });
        const body = opts.format === 'json' ? toJsonExport(rows, { placeId: opts.placeId ?? null }) : toCsv(rows, undefined, { bom: !!opts.out && opts.bom !== false, raw: opts.rawCsv });
        if (opts.out) { writeExport(opts.out, body); console.log(`Exported ${rows.length} reviews to ${opts.out}`); }
        else process.stdout.write(body);
      } finally { closeStore(store); }
    });
  program.command('delete').description('Delete a place, its reviews, and associated job items')
    .argument('[placeId]', 'feature ID').option('--placeId <id>', 'legacy alias').option('--db <path>', 'database path')
    .action(async (placeId, opts) => {
      const id = placeId ?? opts.placeId; if (!id) throw new UsageError('delete needs a feature ID');
      const { createStore } = await import('../core/store.js'); const store = createStore(opts.db ?? DEFAULT_DB);
      try { store.deleteReviews(id); console.log(`Deleted ${id}`); } finally { closeStore(store); }
    });
  program.command('gc').description('Delete reviews older than the requested retention period')
    .requiredOption('--older-than <days>', 'positive age in days').option('--db <path>', 'database path')
    .action(async opts => {
      const days = positiveNumber(opts.olderThan, 'older-than');
      const { createStore } = await import('../core/store.js'); const store = createStore(opts.db ?? DEFAULT_DB);
      try { console.log(`Reviews retained: ${store.retentionVacuum(days)}`); } finally { closeStore(store); }
    });
  program.command('doctor').description('Check runtime, browser, database, and authentication')
    .option('--profile <name>', 'profile name', 'default').option('--db <path>', 'database path')
    .option('--language <code>', 'UI language', 'en').action(async opts => {
      const { doctor } = await import('./doctor.js'); const result = await doctor(parseRunOptions(opts));
      if (!result.ok) process.exitCode = 1;
    });
  program.command('serve').description('Start the localhost dashboard')
    .option('--port <n>', 'port, default 7877').option('--db <path>', 'database path')
    .action(async opts => {
      const port = opts.port == null ? 7877 : positiveNumber(opts.port, 'port', { integer: true, min: 1, max: 65535 });
      const { createDashboardServer } = await import('../dashboard/server.js');
      createDashboardServer({ dbPath: opts.db ?? DEFAULT_DB, port });
    });
  return program;
}
