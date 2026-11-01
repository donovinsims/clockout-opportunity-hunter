# Opportunity Hunter

A manual prospecting engine for Clockout. It researches public business websites, saves evidence, measures phone usability, scores potential opportunities, keeps a deduplicated local tracker, and prepares unsent owner-reviewed outreach drafts.

## Run

```sh
cd /Users/forex/Clockout-Opportunity-Hunter
./hunt run
./hunt status
```

With configured search keys, `run` searches for local electrical, tree-service and plumbing businesses. Tavily is first; Brave is the fallback. Search results are candidates, never qualification evidence. Up to three queries and 30 distinct domains are researched per run. If search is unavailable, saved public candidates can still be audited.

```sh
./hunt run --query 'Roscoe Illinois independent tree service' --city Roscoe
./hunt run --candidates data/candidates.json
./hunt run --directory 'https://a-public-directory.example/members' --city Rockford
./hunt discover --directory 'https://a-public-directory.example/members' --city Rockford
```

The example directory URL is a placeholder, not a configured source. Directories that block automated access are skipped. A candidate JSON file is an array of `{ "name": "Business name", "city": "Rockford", "industry": "electrical contractor", "website": "https://official-business.example/", "discovery_source": "public URL or query" }`. City must be one of the eight configured territory cities. The engine requires a matching street address and ZIP, or a phone-matched indexed public listing, rather than a service-area mention. Indexed listings can be stale and are labeled as such. Use one city per query batch; ambiguous businesses remain on review hold.

The Mac already had Python 3.13, Beautiful Soup 4.15 and Playwright 1.60 installed. The owner approved adding axe-core 4.14.0 locally for standard accessibility checks; it is pinned in package-lock.json. Website audits use installed Google Chrome with a separate sandboxed profile inside `data/`; they never use the owner's everyday logged-in Chrome profile. `--no-browser` performs HTTP research and leaves browser findings unverified. A phone-sized viewport and Android mobile user agent are both set for mobile checks.

## Results

- `data/hunter.sqlite3`: durable local tracker, run state, human sales fields, integration receipts.
- `data/prospects.csv`: all researched businesses and qualification reasons, with source URLs and next actions.
- `data/latest-report.md`: owner review report.
- `data/runs/<run-id>/`: per-run summary and individual audit JSON records.
- `data/evidence/`: source HTML with SHA-256 identifiers, browser measurements and mobile screenshots.
- `data/drafts/`: complete personalized drafts for the three strongest current qualified email-ready records; no email is sent. Phone-only prospects receive local call outlines in `data/outreach/`.
- `logs/hunter.jsonl`: structured candidate events. Failed and interrupted runs remain visible.

All of these remain inside this project and are ignored by Git. The separate GitHub repository is private. No project files were committed or pushed.

## Scoring and review

See [the rubric](docs/scoring.md). Qualification requires at least 70/100, a verified important website problem, service and commercial evidence, an independent-ownership signal, a verified territory mention, a public contact, no closure/franchise signal, and no unresolved identity collision. Owner budget, decision-maker access, intent to buy and delivery timing are unknown until a conversation.

The audit is deliberately bounded. It checks real rendered phone layout on the main and contact pages, plus axe-core label and text-contrast rules; it records sources and fetch failures. It does not submit customer forms, claim real-user performance metrics, certify accessibility, or infer a broken website from a blocked request. A site can be correctly rejected even when its design looks old.

Record a human sales status without losing it on future research:

```sh
./hunt mark PROSPECT_ID --status 'do not contact'
./hunt mark PROSPECT_ID --status contacted --follow-up 2026-11-06
./hunt export
```

Deduplication uses normalized name/city and domain. Contact matches with different business identities are flagged for review, never silently merged. Research updates do not overwrite human sales statuses or follow-up dates. CSV cells are escaped against formula injection. Historical source files and stale drafts are retained for auditability. Persistent `data/review-holds.json` excludes uncertain business identities or evidence from future qualification until reviewed.

## Search keys

`.env` is ignored and owner-readable only. It contains `TAVILY_API_KEY`, `BRAVE_API_KEY`, and optional `OPPORTUNITY_GOOGLE_ACCESS_TOKEN`. Tavily remains the default even when only the Brave key is presently configured. Credentials never belong in candidate JSON, reports or Git. Provider errors are summarized without returning keys. API calls use existing account allowances; the engine creates no subscription.

## Optional integrations

The local engine does not depend on any integration.

- **Google Sheets:** a Codex-assisted import can create the native CRM from the local export. Standalone syncing requires a Google access token with Sheets access plus the existing `google_sheet_id` in ignored `config/local.json`. Use the `OpportunityHunter` tab and preserve its header. Existing human outreach status and follow-up columns are not written during refresh.
- **Gmail:** Codex's connected Gmail plugin can create drafts. Standalone `sync` needs a Google access token with draft permissions. Draft creation is idempotent by prospect ID; uncertain network outcomes require reconciliation instead of blind retries. Recipients without verified email addresses keep a local draft and a public-phone next action.
- **Hermes/Telegram:** the manual command and safe integration instructions are in [docs/hermes.md](docs/hermes.md). Existing Hermes configuration is read only. No gateway changes or recurring jobs are installed.

```sh
./hunt sync --sheets
./hunt sync --gmail
# Explicit owner notification only; never prospect outreach:
./hunt sync --telegram-run RUN_ID --hermes-env /Users/forex/.hermes/.env
```

No sender, scheduler, form submission, website publisher or appointment-booking command exists. A future weekday 8 AM America/Chicago schedule requires separate approval.

## Verify

```sh
python3 -m unittest discover -s tests -v
```

Canonical context was read from `/Users/forex/Clockout-Context-Files-MASTER-2026-10-29/docs`, including current state, website offer, sales operating system, market qualification, brand voice and tool register. Source hashes are retained locally to check that it stayed unchanged. The attached implementation prompt informed requirements; the user's independent-project, local-first and no-outreach instructions control this implementation.

## Verified delivery status — October 30, 2026

The final location-checked cycle researched six candidates, qualified five, updated six existing records and created zero duplicates. Sixteen automated checks passed, including an actual Chrome/axe-core fixture test. See `data/owner-report.md` for the five prospects, evidence and next actions.

The private Google Sheets tracker is verified through connector readback and a native browser check. Three current Gmail drafts for Bove’s, Thiele and Gauerke were created or updated and read back with the DRAFT label. Gauerke’s recipient is blank until the business email is confirmed. Charlie O’s was put on a location hold and replaced by Busy Beaver Tree Care in the active prospect list. No outreach was sent. These connector-assisted cloud writes do not configure standalone Google OAuth; future automatic CLI syncing needs a Google access token. Telegram bot access was verified with getMe; no notification was sent.

The Brave key was added only to this project’s ignored `.env` (mode 0600). Tavily remains first in provider order and awaits its key. All 95 canonical context files match their initial hashes. The separate private GitHub repository is empty; no commits or pushes were made.

The owner confirmed the territory is strictly Roscoe, Rockton, Rockford, South Beloit, Loves Park, Machesney Park, Belvidere and Beloit. Nearby towns are excluded, even when a business advertises service in the target area.

## Optional Google Maps discovery

```sh
./hunt discover --maps --query "electricians" --city Roscoe --limit 10 --output data/maps-candidates.json
./hunt run --candidates data/maps-candidates.json --limit 10
```

This manual discovery provider uses installed Playwright and isolated Chrome. It does not
use the owner's signed-in profile, proxies, stealth packages or third-party launchers.
Each query stops after ten listings, five scrolls or 120 seconds. Partial results,
public HTML snapshots, collection times and errors remain in `data/maps/`.
A candidate file does not establish qualification. Maps website links can be missing;
the audit searches for an official site and requires matching public phone and business
name before using it. Unresolved websites stay on review, never become a "no website" pitch.
Only the eight configured towns qualify; the query town does not establish an address.

The CRM preserves its original 18 columns and appends Maps URL/category/rating/review count/
observation time and published emails/sources/verification status. Blank rating/count means
unknown. Google can expose a limited view that hides review counts; no count is inferred
from stars or search snippets. Published email does not establish inbox delivery or owner identity.
Maps fields do not directly add scoring points. Audit findings remain readable summaries,
and outreach angles tie a specific observation to a personal, unsent conversation opener.

Sheets sync maps columns by headers, preserves owner status/follow-up and unknown columns,
and stops on conflicting headers, duplicate IDs, insufficient grid bounds or incomplete writes.
Connector-assisted updates do not configure standalone OAuth. Core exports work without Google.
Third-party attribution: [notices](docs/third-party-notices.md).

## Optional review signals

`./hunt export --review-signals signals.json` adds an informational section from the separate gmr review scraper. It never changes scores. See [docs/review-signals.md](docs/review-signals.md).

## Optional review research

Review collection is a manual supplementary step. It uses the pinned source snapshot
in `vendor/reviews` and owner-approved Node dependencies, installed without lifecycle
scripts or browser downloads. It uses the installed Chrome and a separate profile at
`data/profiles/opportunity-hunter`. Website audits continue to use their anonymous
mobile profile. No owner's everyday browser profile or cookies are copied.

### Required before every signed-in review run

The AI agent must run both commands below before each signed-in review collection,
even when the dedicated browser already appears open:

```sh
cd /Users/forex/Clockout-Opportunity-Hunter
./hunt reviews --login
./hunt reviews --doctor
```

`--login` opens or reuses the dedicated normal Chrome session; it does not force a
fresh sign-in or restart an existing session. Proceed only when `--doctor` exits
successfully and reports both `status: ready` and `auth_state: signed-in`.

If authentication is missing, ask the owner to sign into Maps in that same dedicated
window and leave it open. The owner handles credentials and any authentication
prompts. After the owner finishes, rerun `--doctor` once; do not repeatedly rerun
`--login`. If verification still fails, stop signed-in review collection and report
that reauthentication or session investigation is required. Treat a failed check,
expired session or access challenge as incomplete access, never as an empty history.
Do not restart Chrome in a login loop, clear cookies/session data, delete lock files,
change browser security settings or silently switch to anonymous collection.

After successful verification, choose one collection command:

```sh
./hunt reviews --qualified --limit 10 --timeout 90
./hunt reviews --prospect BUSINESS_ID --limit 10 --timeout 90
```

The collector attaches to the live session and leaves normal Chrome open. Keep it
open throughout collection. If the owner closes it, repeat the required sequence
before the next signed-in review run. A legacy-window/profile-lock problem requires
owner attention; the agent must report it rather than repeatedly restarting Chrome.

Signing in can expose more reviews than anonymous access, but does not guarantee a
complete history. Retain collection limits and label capped or interrupted results
as samples or incomplete. Signed-in collection in this integration remains unverified
until a successful live sample is recorded in `docs/reviews-and-backups-validation.md`.

These Google sign-in prerequisites apply only to signed-in review collection.
Ordinary prospect research, Maps discovery and website audits work independently;
website audits retain their separate anonymous mobile profile. Anonymous review
collection requires an explicit owner request and must not be used as a silent fallback:

```sh
./hunt reviews --qualified --anonymous --limit 5 --timeout 40
```

Collection is bounded to five selected businesses per invocation, 1–30 reviews per
business and a 10–120 second hard deadline per business. Signed-in collection requires
verified authentication; anonymous mode is explicit. Expired sign-in, blocked access,
wrong/missing business identity, unavailable modules and incomplete sorting/coverage
are reported rather than treated as empty review histories. A `limit-reached` result
is a sample, not a complete history. Exit 2 means at least one collection was incomplete.

Reports: `data/reviews/latest-report.md`; raw evidence and partial streaming results
remain in per-attempt folders. Review IDs deduplicate repeat observations in local
prospect payloads. Review text is untrusted third-party testimony. Keyword signals
are labeled for human corroboration; they do not add score, change qualification,
replace website findings, or create/send outreach. Reviewer names/profile URLs are
omitted from adapter output. Existing CRM columns and human sales state are preserved.

The kit-inspired network-response parser fills missing Maps fields only after matching
stable place identity or name plus public phone. It shares Google's access limitations;
it does not retry around a challenge or start a separate scraping service. Source and
license details are in `docs/third-party-notices.md`.
