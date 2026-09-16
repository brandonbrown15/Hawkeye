# Remote monitoring & intervention

**Short answer:** Once Autocode is live on the Jetson, you can watch it, pause it, and **talk to the model** from your phone — not only overnight.

## How to watch

| Channel | What you get | Setup |
|---------|--------------|--------|
| **Notion** | Build Queue, Agent Runs, Escalation Log | Required for live autopilot |
| **Telegram** | Cycle start / per-task route / pause-abort / digest | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| **Tailscale + UI** | Live dashboard, controls, **LLM chat** | Install Tailscale; `./scripts/ui.sh --remote` |

Recommended path: **Tailscale** on the Jetson. Notion is the task board; Telegram is the pager; the UI is the live control panel ([ui.md](ui.md)). Always-on coding: [continuous.md](continuous.md).

```bash
# On Jetson (one-time)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Then from anywhere:

```bash
ssh jetson
cd /opt/autocode   # or your clone path
./scripts/ui.sh --remote        # dashboard on Tailscale IP
# or tunnel from your laptop:
#   ssh -L 8787:127.0.0.1:8787 jetson
./scripts/status.sh
tail -f logs/worker-*.log logs/nightly-*.log
```

## Give the model instructions remotely

Open the Tailscale UI URL (or Hawkeye domain after login) on your phone/laptop → **Talk to Autocode / Hawkeye**.

- Messages hit the **local** Ollama model on the Jetson first (free all day)
- Hard asks escalate to **Cursor** then **Grok Bot** (webhooks), then optional API keys
- You can optionally add follow-ups to the Notion Ready checklist from chat

Personal private deploy: [hawkeye.md](hawkeye.md).

## Always-on coding (not just overnight)

```bash
# in .env after a supervised run
AUTOCODE_AUTOPILOT_ENABLED=1
AUTOCODE_CONTINUOUS_ENABLED=1
AUTOCODE_DRAIN_UNTIL_EMPTY=1

./cron/install_autopilot_timers.sh
# overnight @ 01:00 + worker every ~30 min + UI service
```

## Pause / abort / skip remotely

From the UI, Telegram, or SSH:

```bash
./scripts/control.sh pause
./scripts/control.sh resume
./scripts/control.sh abort
./scripts/control.sh skip BLD-12
```

Pause blocks **between** tasks. Abort finishes the current step then stops the cycle.

## Telegram

When configured, Autocode can ping:

- cycle start / finish  
- per-task route  
- pause / abort  

Disable chatter: `AUTOCODE_TELEGRAM_PROGRESS=0`

## If something looks stuck

1. Check UI stuck indicator / heartbeat age  
2. `tail -f logs/worker-*.log` — Hermes hung? Ollama down?  
3. `./scripts/doctor.sh`  
4. Pause, fix, resume — or abort and re-queue in Notion  

## Honest readiness

| Goal | Ready? |
|------|--------|
| `./scripts/demo_night.sh` (mock) | Yes — no Jetson AI / Notion needed |
| Live always-on coding | After go-live checklist (Hermes, Notion, optional cloud keys) |
| Remote monitor + chat once live | Yes — this doc + Tailscale + UI |
