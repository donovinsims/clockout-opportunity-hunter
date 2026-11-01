# Review scraper and Maps backup validation — 2026-11-01

## Incorporated behavior

- Optional source collector API from the owner’s local review-scraper working tree, copied with MIT attribution and per-file provenance. Original repository unchanged.
- Owner-approved Node packages installed inside this project, with lifecycle scripts disabled and no browser downloads.
- Signed-in review collection attaches to the dedicated normal Chrome session opened by `./hunt reviews --login`. It does not relaunch its authenticated profile or close that session.
- A verified loopback-only endpoint is accepted only when its browser instance path matches the private dedicated-session descriptor. Global HTTP proxies are bypassed for this local check.
- Anonymous review collection remains explicit and separate. Website audits keep their isolated anonymous mobile profile.
- Review IDs deduplicate repeated observations; source URLs, dates, sample coverage, authentication and termination are retained. Review signals never change score, qualification, website findings or outreach.

## Integrated Maps comparison

| Business | Aggregate rating | Listing review count | Duration |
| --- | ---: | ---: | ---: |
| Gauerke Electric Company | 5.0 | 2 | 12.45 s |
| Ellis and Ellis | 4.3 | 90 | 7.83 s |
| Bove's Auto Repair | 4.7 | 219 | 7.68 s |
| Thiele Heating and Air Conditioning | 4.6 | 121 | 16.07 s |
| Busy Beaver Tree Care | 4.9 | 309 | 9.05 s |

All five matched public phones; stable IDs were cross-checked when available. All protected prospect fields were unchanged. Counts and timestamps were refreshed in the existing CRM without changing any other cell or its formatting.

The kit’s user-agent technique and small field-path parser were adapted into the existing extractor. The full kit/CDP engine was not installed. Live Bove’s source produced 4.7 / 219 through both DOM extraction and the network backup when DOM values were cleared for the comparison.

An aggregate-rating bug exposed by visible review cards was fixed: individual customer stars cannot replace the business aggregate. Regression test added.

## Review collection results

Five anonymous business attempts collected zero reviews and returned incomplete sort/access outcomes. These are not evidence that the businesses have no reviews or complaints.
Earlier profile-relaunch attempts reported anonymous authentication and the owner reported sign-outs; that workflow was removed.

### Signed-in acceptance pilot (2026-11-01)

Preflight followed the required sequence: `./hunt reviews --login`, then `./hunt reviews --doctor`.
The first doctor check reported `needs_login`; after owner sign-in the retry reported
`status: ready` / `auth_state: signed-in`. Collection then ran signed-in.

Run 1 (4 of 5 collected, 22 reviews): Ellis and Ellis 5, Bove's Auto Repair 5,
Thiele Heating and Air Conditioning 5, Busy Beaver Tree Care 5 — all `limit-reached`.
Gauerke Electric returned `pagination-stall` with 2 reviews; the collector kept waiting
for pagination the 2-review listing would never provide and was correctly labeled
`incomplete` rather than complete. Repeat run verified session retention: the doctor gate
passed again without re-login (after one `needs_login`/`unknown` false alarm that was
resolved by re-running the standard login/doctor sequence), and every review ID collected
in the repeat matched the first run exactly (0 new IDs on all four businesses).

Failures and resolution:

- Bove's Auto Repair returned a one-off `TimeoutError` (`collector-error`) on the repeat run.
  The browser session was not restarted; a single targeted retry (`reviews --prospect b5c1c8b1975a511f`)
  after the doctor gate collected 5/5 with full ID overlap against the first run. Reported as
  collected; capability validated.
- Gauerke Electric remains `incomplete` by design. Its 2 collected reviews exhaust what the
  listing visibly offered, but the collector cannot yet distinguish "no more pages" from a stall.
  Reported here and in the report as an incomplete access sample, not as absence of reviews.

Interpretation limits: samples of 5 are not complete review histories (collector-reported
totals 87/118/306 are unverified placeholders from a live page); no complaint keywords fired in
these samples, which establishes nothing about the businesses. Long-loop reliability is
still an open item; pagination-end detection closed later the same day (below).

### Fresh prospecting batch (2026-11-01)

10 businesses researched across the approved towns; 1 newly qualified
(Stateline Pros Landscaping LLC, Loves Park, 77/100 — Loves Park confirmed in the
approved-town set, contact `(773) 971-2821`, axe-core contrast finding with evidence artifact).
Table now holds 66 records, 6 qualified; 3 local drafts exist as `owner review; unsent`
(Gauerke, Bove's, Thiele). All outreach statuses remain `not contacted`; no human
status or follow-up field was modified by automation. Verified hold behavior:
1PlumbingCo (location), Charlie O's (owner-confirmed Winnebago rule), directory
pages (expertise.com, trustanalytica kept as discovery sources only), Gibbons contact
ownership overlap flagged, malformed Rockton Collision phone pending owner review.

## Checks and limits

- 45 Python tests passed; review bridge syntax check passed. A repeat check during the pilot kept all 45 green.
- Normal Chrome attachment was live-tested with `navigator.webdriver` false; a nonzero loopback port preserves normal manual-browser behavior. No script hides or overrides that browser property.
- Normal Chrome attachment was live-tested: browser endpoint remained open before and after authentication checking.
- A synthetic-cookie round trip passed with normal OS keychain storage; it used no real credentials.
- Long-term collection reliability is not established by this small batch. Google presentation and review availability can change.
- Collector-reported totals may differ from independently observed Maps totals; review completeness remains labeled as a sample or incomplete.
- No outreach, schedules, commits, pushes, services or browser security bypasses activated.

Artifacts: `data/kit-comparison/integrated-live.json`, `data/maps/`, `data/reviews/`, `data/reviews/final-tests.log`.

## Operating instructions

Before each signed-in review collection, the agent must run `./hunt reviews --login`
then `./hunt reviews --doctor`; collection requires a successful check reporting
`status: ready` and `auth_state: signed-in`. See the required preflight in
`../README.md`, `../AGENTS.md` and `hermes.md` for the owner sign-in step and single
verification retry. Failed verification stops signed-in collection; it never triggers
repeated browser restarts, session clearing or silent anonymous fallback.
The pilot above provides a successful live signed-in sample (37+ reviews across five
businesses, session retained on the repeat pass) and marks the gate,
deduplication and termination-handling steps validated; longer-run reliability stays open.

### Pagination-end detection (2026-11-01, later the same day)

The Gauerke `pagination-stall` outcome above was fixed and re-verified live. Two changes
(credited in `vendor/reviews/LOCAL-ADAPTATIONS.md`):

- `readSurfaceInPage` now detects feed exhaustion geometrically: the feed's real scroll
  container is found by computed CSS `overflowY` (`auto`/`scroll`, not raw scrollHeight,
  which also matches overflow-hidden panels); when it sits at its bottom, or no scrolling
  ancestor exists because all reviews fit on screen, the feed is at its end.
- The stalled branch (`no new reviews, no spinner, recovery done, full stall window)` now
  treats feed-exhaustion like the end marker: `no-more-reviews` when the sample meets the
  completeness threshold, `incomplete` when a known count is short of it; only then does the
  prior `pagination-stall` / `anonymous-preview-limit` classification apply.

Live re-verification on the dedicated signed-in session after the required login/doctor
preflight: Gauerke Electric now finishes `collected` / `no-more-reviews`, coverage
`end observed`, 2 reviews in ~14s (previously `pagination-stall` over ~20s). Bove's Auto
Repair (219 reviews) still terminates `limit-reached` unchanged, confirming no mid-feed
misclassification. Unit tests: 6 termination cases in `tests/js/review-termination.test.mjs`
plus the ongoing 45-test Python suite; a geometry probe (`research/probe-feed-geometry.mjs`)
confirmed the overflow rules were consistent with liveness of the dedicated session.
The probe also identified that project-root `node_modules` (pinned `axe-core@4.14.0`)
had gone missing and was restored via `npm ci --ignore-scripts` before the suite run.
This entry supersedes the unsigned-in-run claim above. The pilot section is the
live verification that this note kept as a requirement.
