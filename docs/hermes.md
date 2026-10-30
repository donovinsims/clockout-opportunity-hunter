# Manual Hermes handoff

The existing Hermes gateway/configuration is not modified. Ask the existing Hermes agent to execute this exact manual command when desired:

```sh
cd /Users/forex/Clockout-Opportunity-Hunter && ./hunt run
```

The OS file lock prevents overlapping research cycles. The command returns counts, qualification reasons and local report paths. Read `data/latest-report.md`, `data/prospects.csv` and current local drafts before deciding on outreach.

A completion notification helper can read only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` from the existing `/Users/forex/.hermes/.env`; it never copies them to this project. It sends one concise owner report only when explicitly invoked with `./hunt sync --telegram-run RUN_ID --hermes-env /Users/forex/.hermes/.env`. Confirmed delivery stores Telegram's returned message ID. An uncertain delivery is reserved for manual reconciliation instead of automatic resend. No polling loop, slash-command registration, gateway restart, scheduled task or recurring execution is installed.

The implementation can check bot access with Telegram `getMe` without sending a message. Bot reachability is distinct from confirmed notification delivery. Existing Codex Google connectors are session tools, not credentials automatically available to a standalone Hermes process; standalone Google syncing needs its own authorized Google token.
