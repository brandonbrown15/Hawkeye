# Supervised first overnight run

Full zero→live list: [go-live.md](go-live.md).

Before enabling unattended cron:

1. Run `./scripts/bootstrap_jetson.sh` + `./scripts/doctor.sh` (no FAILs).
2. Confirm Phases 0–2 green (SSH, Ollama coder model, Hermes smoke, Telegram ping).
3. Set `CURSOR_API_KEY` (and optionally `GROK_BOT_WEBHOOK_URL`) and use `delegate_cursor.sh` / `delegate_grok.sh` (not stubs).
4. Put **one** tiny Ready + Local-safe task in Build Queue.
5. Stay nearby and run: `./cron/overnight_run.sh --force`
6. Verify:
   - Branch created (not on `main`)
   - Checks ran
   - PR opened **or** Escalation Log written (Cursor or Grok Bot)
   - Agent Runs row exists
   - Telegram digest received
7. Second night: one Cloud-only task to confirm cheaper-first cloud handoff.
8. Only then: set `AUTOCODE_AUTOPILOT_ENABLED=1`, raise `AUTOCODE_MAX_TASKS_PER_NIGHT` if desired, and leave the timer enabled.
