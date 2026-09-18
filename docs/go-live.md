# Fully automatic go-live

## Easiest path (recommended)

```bash
git clone https://github.com/brandonbrown15/Autocode.git
cd Autocode
./start
```

That asks a few questions, then installs everything.
See **[START_HERE.md](../START_HERE.md)**.

---

## Advanced: one-shot without the wizard

Put secrets in `.env` once, then:

```bash
./scripts/go_live.sh --local-only --first-night --enable-autopilot
```

What `go_live.sh` does automatically:

1. Detect / layout **data SSD** (models, workspaces, 16G swap) via `bootstrap/05_use_data_ssd.sh`
2. Bootstrap (MAXN, Ollama into `OLLAMA_MODELS`, Hermes, gh, Tailscale, doctor)
3. Non-interactive `gh` auth via `GITHUB_TOKEN`
4. Clone `WORKSPACE_REPOS`
5. **Provision** Notion DBs under `NOTION_HUB_PAGE` + seed a Ready Local-safe task
6. Mock night + doctor gate
7. Optional first live night (`--first-night`)
8. Optional timer enable (`--enable-autopilot`)

### 4TB SSD tip

Mount it (e.g. `/mnt/nvme`), then either set `AUTOCODE_DATA_ROOT=/mnt/nvme/autocode` in `.env` or let `05_use_data_ssd.sh` auto-pick a mount with ≥100GB free. That keeps multi-GB coder weights and swap off the root filesystem.

---

## Recommended `.env`

```bash
AUTOCODE_AUTOPILOT_ENABLED=0
AUTOCODE_LOCAL_ONLY=1                  # until webhooks are set
AUTOCODE_COST_PROFILE=cursor-grok
AUTOCODE_CLOUD_PREFERENCE=cursor
AUTOCODE_DISABLE_METERED_GROK=1
AUTOCODE_CURSOR_DELEGATE_CMD=./scripts/delegate_cursor.sh
AUTOCODE_GROK_DELEGATE_CMD=./scripts/delegate_grok.sh
NOTION_TOKEN=...
NOTION_HUB_PAGE=...
GITHUB_TOKEN=...
WORKSPACE_REPOS=owner/repo
# CURSOR_WEBHOOK_URL=...
# GROK_BOT_WEBHOOK_URL=...
# Leave empty overnight:
# XAI_API_KEY=
# ANTHROPIC_API_KEY=
```

Cheaper-first ladder: **Local → Cursor Cloud → Grok Bot → Human**.

---

## Checklist (mostly automated)

### A–B. Host + local AI

Handled by `./scripts/bootstrap_jetson.sh` (also run from `go_live.sh`).

### C. Notion

- [ ] Integration created
- [ ] One empty hub page shared with the integration → `NOTION_HUB_PAGE`
- [ ] `python3 notion/client.py provision --seed` (or `go_live.sh`) creates the three DBs + first Ready task
- [ ] `python3 notion/client.py doctor` passes

### D. GitHub / workspaces

- [ ] `GITHUB_TOKEN` set **or** `gh auth login` once (`./scripts/auth_github.sh`)
- [ ] `WORKSPACE_REPOS=...`
- [ ] `./scripts/clone_workspaces.sh` (also from `go_live.sh`)

### E. Cloud delegates (optional at first)

| Target | Env | Script |
|--------|-----|--------|
| Cursor Cloud | `CURSOR_API_KEY` (preferred) or `CURSOR_WEBHOOK_URL` | `./scripts/delegate_cursor.sh` |
| Grok Bot | `GROK_BOT_WEBHOOK_URL` | `./scripts/delegate_grok.sh` |

Use `--local-only` until these are set. Scripts **fail honestly** if the API key / URL is missing when cloud escalate is chosen.

### F. Remote ops

- Tailscale (`./bootstrap/04_install_tailscale.sh` then `sudo tailscale up`)
- Telegram: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- `./scripts/control.sh pause|resume|abort|skip <id>`

### G. Enable overnight

```bash
./scripts/go_live.sh --skip-bootstrap --first-night --enable-autopilot
# or manually:
#   AUTOCODE_AUTOPILOT_ENABLED=1
#   ./cron/install_autopilot_timers.sh
```

Timer no-ops while `AUTOCODE_AUTOPILOT_ENABLED!=1`.

---

## Already automated in-repo

- One-shot `./scripts/go_live.sh` + `./scripts/bootstrap_jetson.sh` + `./scripts/doctor.sh`
- Notion **provision + seed**
- Non-interactive GitHub auth via token
- Real Hermes install + local Ollama config + smoke
- Honest webhook delegates
- Autopilot safety gate + timer install
- Mock demo + unit tests + remote pause/abort

## Still on you (once)

1. Notion integration + share the hub page  
2. Put tokens in `.env` on the Jetson  
3. Optional: Cursor / Grok Bot webhook URLs for cloud escalate  
4. `sudo tailscale up` if you want phone SSH  

Mock mode (`./scripts/demo_night.sh`) works with zero Notion/Jetson hardware.
