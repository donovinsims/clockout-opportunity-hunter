# Optional review signals

Informational enrichment from the separate gmr review scraper. No scraper code runs inside Opportunity Hunter.
Signals never change the verified score, qualification, findings or outreach angle.

```sh
# 1. In the scraper repo (headed, signed-in profile, owner supervised):
node src/cli/index.js run maps-urls.txt --profile default --limit 100 --sort newest --db data/pilot.db
node src/cli/index.js signals --db data/pilot.db --out signals.json
# 2. In Opportunity Hunter:
./hunt export --review-signals /path/to/signals.json
./hunt run --candidates data/maps-candidates.json --review-signals /path/to/signals.json
```

Join order: Maps place id (from `maps_cid` or `maps_url`), marked confirmed; then business name plus town
(`town` field in the signals entry, if present), marked unconfirmed. Unmatched prospects get no section.

Output: a separate "Review signals" section at the end of `data/latest-report.md` and `data/review-signals.csv`
(id, name, city, join, job status, strength, counts, signal topics, top quote with date and review id).
`data/prospects.csv` and the Sheets columns are unchanged.

Strength: strong (at least one explicit complaint), weak (only indirect hints such as "had to call",
"wish they had", missing responsiveness praise, or no website on the Maps listing), none-found (complete scan,
nothing matched), incomplete (scraper job partial or failed; never read as "no complaints").

A missing or malformed file prints a warning, is recorded in the run summary, and the run continues.
Every quote is a keyword match and must be read by the owner before it is used in outreach.
