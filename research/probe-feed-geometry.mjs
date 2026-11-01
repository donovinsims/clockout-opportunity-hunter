// One-off geometry probe for the review feed scroll containers on the live dedicated Chrome session.
// Diagnostic only; it changes nothing and closes only this probe tab.
import { chromium } from '../vendor/reviews/node_modules/rebrowser-playwright/index.mjs';
import { SELECTORS } from '../vendor/reviews/src/collector/selectors.js';
import { readSurfaceInPage, scrollInPage } from '../vendor/reviews/src/collector/place-reviews.js';

const url = process.argv[2];
if (!url || !/https:\/\/www\.google\.com\/maps/.test(url)) throw new Error('Pass a Google Maps place URL');
const browser = await chromium.connectOverCDP('http://127.0.0.1:58439', { timeout: 15000 });
const context = browser.contexts()[0];
const page = await context.newPage();
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.locator('h1.DUwDvf, h1.fontHeadlineLarge').first().waitFor({ timeout: 8000 }).catch(() => {});
  const tab = await page.locator(SELECTORS.reviewsTab).first();
  if (await tab.count()) { await tab.click({ timeout: 10000 }); await page.waitForSelector(SELECTORS.card, { timeout: 10000 }).catch(() => {}); }
  // Reproduce the collector loop: toward-bottom scroll then re-read.
  for (let i = 0; i < 3; i++) {
    await page.evaluate(scrollInPage, { selectors: SELECTORS });
    await page.mouse.wheel(0, 2500);
    await page.waitForTimeout(1000);
  }
  const surface = await page.evaluate(readSurfaceInPage, { selectors: SELECTORS });
  const geometry = await page.evaluate(({ selectors }) => {
    const cardRoot = selectors.cardFallback ?? selectors.card;
    const firstCard = [...document.querySelectorAll(cardRoot)].find(el => !el.parentElement?.closest(cardRoot)) ?? null;
    if (!firstCard) return { firstCard: false };
    const feed = firstCard.closest(selectors.feed) ?? firstCard.parentElement;
    const chain = [];
    for (let node = feed; node && chain.length < 25; node = node.parentElement) {
      chain.push({
        tag: node.tagName, cls: (node.className ?? '').toString().slice(0, 60),
        scrollHeight: node.scrollHeight, clientHeight: node.clientHeight, scrollTop: node.scrollTop,
        overflowY: getComputedStyle(node).overflowY,
        scrollable: node.scrollHeight > node.clientHeight + 100 && node.clientHeight > 100,
      });
    }
    const se = document.scrollingElement ?? document.documentElement;
    chain.push({ tag: 'scrollingElement', scrollHeight: se.scrollHeight, clientHeight: se.clientHeight, scrollTop: se.scrollTop, scrollable: se.scrollHeight > se.clientHeight + 100 && se.clientHeight > 100 });
    return { firstCard: true, feedTag: feed?.tagName, feedClass: (feed?.className ?? '').toString().slice(0, 60), chain, spinnerBusy: [...document.querySelectorAll('[role="progressbar"],[aria-busy="true"]')].map(n => ({ hidden: !!n.hidden, ariaHidden: n.getAttribute('aria-hidden') })) };
  }, { selectors: SELECTORS });
  console.log(JSON.stringify({ name: surface.name, endMarkerSeen: surface.endMarkerSeen, feedAtEnd: surface.feedAtEnd, expected: surface.expected, spinnerVisible: surface.spinnerVisible, cardCount: surface.cardCount }, null, 2));
  console.log(JSON.stringify(geometry, null, 2));
} finally {
  await page.close().catch(() => {});
  process.exit(0); // disconnect only this client; the user's session stays open
}
