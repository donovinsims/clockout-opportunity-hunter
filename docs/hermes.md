# Manual Hermes handoff

The existing Hermes gateway/configuration is not modified. Ask the existing Hermes agent to execute this exact manual command when desired:

```sh
cd /Users/forex/Clockout-Opportunity-Hunter && ./hunt run
```

The OS file lock prevents overlapping research cycles. The command returns counts, qualification reasons and local report paths. Read `data/latest-report.md`, `data/prospects.csv` and current local drafts before deciding on outreach.

A completion notification helper can read only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` from the existing `/Users/forex/.hermes/.env`; it never copies them to this project. It sends one concise owner report only when explicitly invoked with `./hunt sync --telegram-run RUN_ID --hermes-env /Users/forex/.hermes/.env`. Confirmed delivery stores Telegram's returned message ID. An uncertain delivery is reserved for manual reconciliation instead of automatic resend. No polling loop, slash-command registration, gateway restart, scheduled task or recurring execution is installed.

The implementation can check bot access with Telegram `getMe` without sending a message. Bot reachability is distinct from confirmed notification delivery. Existing Codex Google connectors are session tools, not credentials automatically available to a standalone Hermes process; standalone Google syncing needs its own authorized Google token.

## Required review authentication preflight

For every signed-in review collection, the AI agent (including a manually invoked
Hermes agent) must first run both commands from the project:

```sh
cd /Users/forex/Clockout-Opportunity-Hunter
./hunt reviews --login
./hunt reviews --doctor
```

`--login` opens or reuses the dedicated normal Chrome session without forcing a new
sign-in. Proceed only after `--doctor` exits successfully and reports `status: ready`
and `auth_state: signed-in`. If authentication is missing, ask the owner to sign into
Maps in that same window and leave it open, then rerun `--doctor` once. The owner
handles credentials and authentication prompts. If that check still fails, stop
signed-in review collection and report reauthentication/session investigation required.
Do not repeatedly restart Chrome, clear cookies/session data, delete lock files,
change security settings or silently switch to anonymous review collection.

After successful verification, use the existing bounded collection command:

```sh
./hunt reviews --qualified --limit 10 --timeout 90
```

Keep the dedicated browser open. Preserve collection limits; capped/interrupted
results and access failures remain samples/incomplete, never evidence of no complaints.
Signed-in collection remains live-unverified until a successful sample is recorded
in `reviews-and-backups-validation.md`. Anonymous reviews require an explicit owner
request. Ordinary prospect research, Maps discovery and website audits do not require
Google sign-in. This handoff adds no schedule, gateway change or automatic invocation.
