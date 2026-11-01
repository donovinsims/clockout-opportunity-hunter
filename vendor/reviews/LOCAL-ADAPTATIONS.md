# Opportunity Hunter adaptations

- `src/core/paths.js`: all runtime data and profiles use the Opportunity Hunter project root.
- `src/collector/browser.js`: explicitly retain the Chromium sandbox.
- `src/collector/place-reviews.js` + `src/core/termination.js`: pagination-end detection. The feed's real scroll container is identified by computed CSS `overflowY` (`auto`/`scroll`), not by raw scrollHeight (which also matches overflow-hidden panels). When that container is at its physical bottom — or no scrolling ancestor exists because all reviews fit on screen — and the feed shows no new reviews, no spinner, and completed recovery for the full stall window, the listing is treated as ended using the end marker's completeness rule; short listings whose end-marker text never renders now finish as `no-more-reviews` or `incomplete` instead of `pagination-stall`.
- Original source repository, browser profiles and databases remain untouched.
- Dependencies installed with `npm ci --ignore-scripts --omit=dev`; no browser downloaded.

- Both login/doctor and collection retain macOS credential storage by excluding the mock-keychain/basic-password-store launch defaults. No cookies are copied or exposed.

- The Opportunity Hunter wrapper attaches only to normal Chrome opened by `review_session.py`. Its active profile is never relaunched through Playwright. Login/doctor at the `hunt` interface use that attachment path.

- The wrapper uses a nonzero loopback debugging port and a private session descriptor. No automation-control flag, mock credential store, proxy rotation, CAPTCHA handling or security-disabling switch is applied to manual Chrome.
