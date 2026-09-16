# Always-on project autopilot

Autocode is **not** a night-only bot. It is meant to keep programming from your Notion
project details with little or no user input until the project reaches a finished state.
Overnight batches still help, but the continuous worker is the main loop.

```text
Notion Ready tasks (+ self-fed health/bug/improve items)
        │
        ├─ continuous worker  (~every 30 min, drains Ready queue)
        └─ overnight batch    (01:00, larger batch)
                │
                ▼
        orchestrator → Hermes/Ollama or escalate
                │
                └─ IMPROVE:/BUG: lines → new Ready checklist rows
```

## Enable

In `.env` (after one supervised run):

```bash
AUTOCODE_AUTOPILOT_ENABLED=1
AUTOCODE_CONTINUOUS_ENABLED=1
AUTOCODE_DRAIN_UNTIL_EMPTY=1     # keep going until Ready is empty
AUTOCODE_MAX_TASKS_PER_CYCLE=1   # batch size inside a drain
AUTOCODE_MAX_TASKS_PER_DRAIN=50  # safety cap per tick
AUTOCODE_MAX_TASKS_PER_NIGHT=2   # overnight batch
AUTOCODE_SELF_FEED_ENABLED=1
AUTOCODE_HEALTH_FEED_ENABLED=1
```

Install timers:

```bash
./cron/install_autopilot_timers.sh
```

That installs:
- `autocode-overnight.timer` — daily 01:00
- `autocode-worker.timer` — ~every 30 minutes (drain + health seed)
- `autocode-ui.service` — dashboard (set `AUTOCODE_UI_REMOTE=1` for Tailscale)

## Manual cycles

```bash
./cron/worker_run.sh --force          # drain live Ready queue now
./cron/worker_run.sh --dry-run        # route only
./cron/worker_run.sh --mock           # no Notion/Hermes
./cron/overnight_run.sh --force       # larger overnight-style batch
python3 -m orchestrator.self_feed --health --force
```

Or tap **Run work cycle** in the UI. Use **Talk to Autocode** to give the local model
instructions (auto-escalates to a larger cloud model when needed).

## Self-feed

When Hermes finishes a task and emits `IMPROVE:` / `BUG:` lines, Autocode adds Ready
rows to Notion so the next cycle keeps going. Routine health/bug smoke checks are
seeded on an interval as well.

## Safety

- Both paths share `state/run.lock` — they never overlap.
- Timers no-op until `AUTOCODE_AUTOPILOT_ENABLED=1`.
- Continuous ticks no-op until `AUTOCODE_CONTINUOUS_ENABLED=1`.
- Pause / abort / skip still work via UI, `./scripts/control.sh`, or Telegram.

## Remote watch

See [ui.md](ui.md) and [remote-ops.md](remote-ops.md) — Tailscale + dashboard is the intended phone view.
