# Hawkeye

**Private** BrownHawke Engineering assistant — project manager + chat on your Jetson.

You talk to **one** system. Hawkeye plans, remembers, researches, drives Notion boards, runs a free local coder (`coder-64k`), and escalates hard work to **Cursor** / **Grok Bot**.

This is **not** the public [Autocode](https://github.com/brandonbrown15/Autocode) repo. Autocode stays open-source (Apache-2.0); Hawkeye is proprietary and stays private.

---

## What you get

| Layer | Behavior |
|-------|----------|
| **Notion PM board** | Hawkeye / ROSE / Autocode kanban in the UI; status writes back to Notion |
| **Talk to Hawkeye** | Direct chat with local Ollama; optional Notion seeding |
| **Local Ollama** | `coder-64k` (Qwen2.5-Coder 7B + 64k ctx) branded as Hawkeye |
| **Vector memory** | Chat/decisions on the 4TB SSD (`nomic-embed-text`) |
| **Web research** | Deep page-read lookup + citations in chat |
| **Email inbox** | Resend inbound → local draft → approve to send |
| **Cursor / Grok** | Escalate strenuous asks via webhooks |
| **Login** | `@brownhawke.engineering` work emails only |
| **Per-user accounts** | Profile, encrypted connections, shared projects, DMs |
| **Domain** | Cloudflare Tunnel → `https://hawkeye.brownhawke.engineering` |
| **Boot auto-start** | UI (+ tunnel) come back when the Jetson powers on |

---

## Requirements

- Jetson Orin Nano Super (or similar aarch64 Linux) with JetPack 6.x  
- 4TB NVMe recommended (models, swap, memory, workspaces)  
- GitHub access to this private repo  
- Notion integration shared on **Hawkeye Build Queue** (+ ROSE Projects if used)  
- Optional: Cloudflare account for DNS + Tunnel; Tailscale for private remote UI  

---

## Quick start (Jetson)

**Paste one command at a time.** Do not paste Markdown headings or `# comment` lines from the README into the terminal.

### 0. GitHub auth (required — private repo)

GitHub **does not accept your account password** for `git clone`. Use a Personal Access Token (PAT) or SSH.

**Easiest — PAT over HTTPS:**

1. On a phone/laptop, create a token: https://github.com/settings/tokens?type=beta  
   - Resource owner: **brandonbrown15**  
   - Repository access: **Only select repositories** → **Hawkeye**  
   - Permissions: **Contents** = Read (and Write if you want PRs later)  
2. Copy the token (starts with `github_pat_…`).
3. On the Jetson:

```bash
git clone https://github.com/brandonbrown15/Hawkeye.git ~/Hawkeye
```

When prompted:
- **Username:** `brandonbrown15`
- **Password:** paste the **PAT** (not your GitHub password)

**Or — GitHub CLI (recommended if `gh` is installed):**

```bash
gh auth login
# GitHub.com → HTTPS → Login with a web browser (or paste a token)
gh repo clone brandonbrown15/Hawkeye ~/Hawkeye
```

**Or — SSH** (after you add an SSH key to GitHub):

```bash
ssh-keygen -t ed25519 -C "jetson" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
# Add that public key at https://github.com/settings/keys
git clone git@github.com:brandonbrown15/Hawkeye.git ~/Hawkeye
```

### 1. Bootstrap

```bash
cd ~/Hawkeye
./scripts/bootstrap_jetson.sh
```

(Alternative interactive wizard: `./start`)

```bash
# Work users (brandon@ already seeded in config/users.json)
python3 scripts/set_work_user.py --email teammate@brownhawke.engineering

# Notion
./scripts/connect_notion.sh
# Share the integration on Hawkeye Build Queue + ROSE Projects in Notion

# Local model + embeddings
./ollama/create_coder_64k.sh
ollama pull nomic-embed-text

# Dashboard now
./scripts/ui.sh
# → http://127.0.0.1:8787/

# Survive reboots
./scripts/install_hawkeye_autostart.sh

# Health
./scripts/doctor.sh
```

One-shot go-live (bootstrap + doctor + optional autopilot):

```bash
./scripts/go_live.sh --local-only --first-night --enable-autopilot
```

---

## Full setup

### 1. Clone and bootstrap

```bash
# Recommended — home directory (no root)
git clone https://github.com/brandonbrown15/Hawkeye.git ~/Hawkeye
cd ~/Hawkeye
./scripts/bootstrap_jetson.sh

# Optional — system path (needs sudo for the directory only)
# sudo mkdir -p /opt/hawkeye && sudo chown "$USER:$USER" /opt/hawkeye
# git clone https://github.com/brandonbrown15/Hawkeye.git /opt/hawkeye
# cd /opt/hawkeye && ./scripts/bootstrap_jetson.sh
```

Do **not** paste the `# or any path` comment as part of a broken path — and do **not** clone straight into `/opt/...` without `sudo` / ownership first (`Permission denied`).

What bootstrap does:

1. Dependency check  
2. Data SSD layout (`AUTOCODE_DATA_ROOT`, `OLLAMA_MODELS`, Hawkeye memory dir)  
3. Swap on SSD  
4. MAXN SUPER power mode  
5. `.env` from `.env.example`  
6. Ollama + `coder-64k`  
7. Hermes install + local-primary config  
8. Hermes smoke  
9. GitHub CLI  
10. Optional Tailscale  
11. Clone workspace repos (if configured)  
12. Doctor  
13. **Hawkeye auto-start** (`hawkeye-ui.service`)

Skip auto-start with `--skip-autostart`.

### 2. Configure `.env`

Copy is automatic; edit secrets:

```bash
# Product / auth
AUTOCODE_PRODUCT_NAME=Hawkeye
AUTOCODE_PRIVATE_MODE=1
HAWKEYE_ALLOWED_EMAIL_DOMAIN=brownhawke.engineering
HAWKEYE_USERS_FILE=config/users.json

# Domain (after tunnel)
AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering
AUTOCODE_UI_SECURE=1

# Escalate hard asks (recommended). Flip "Local only" in the UI header anytime
# to force free Jetson Ollama only (persists in state/hawkeye-runtime.json).
AUTOCODE_PERSONAL_LOCAL_ONLY=0
CURSOR_API_KEY=…
# CURSOR_REPOSITORY=https://github.com/brandonbrown15/Hawkeye
# CURSOR_WEBHOOK_URL=https://…  # optional bridge
GROK_BOT_WEBHOOK_URL=https://…

# Notion (from connect_notion / provision)
NOTION_TOKEN=
NOTION_HUB_PAGE=
# Optional overrides — defaults ship for BrownHawke boards
# NOTION_BUILD_QUEUE_DB=
# NOTION_ROSE_PROJECTS_DB=
HAWKEYE_NOTION_USE_DEFAULTS=1

# Memory
HAWKEYE_MEMORY_ENABLED=1
# HAWKEYE_MEMORY_KEY=…long passphrase…
HAWKEYE_EMBED_MODEL=nomic-embed-text

# Optional research provider
# BRAVE_SEARCH_API_KEY=
```

Add teammates:

```bash
python3 scripts/set_work_user.py --email alex@brownhawke.engineering
```

### 3. Notion PM boards

| Hawkeye tab | Notion DB | Env |
|-------------|-----------|-----|
| Hawkeye | Hawkeye Build Queue | `NOTION_BUILD_QUEUE_DB` |
| ROSE Projects | ROSE Projects | `NOTION_ROSE_PROJECTS_DB` |
| Autocode | LCM Build Queue | `NOTION_LCM_BUILD_QUEUE_DB` |

Without `NOTION_TOKEN`, the UI shows sample cards (`HAWKEYE_PM_MOCK=1` forces mock).

Team flow:

1. Put work in Notion (Status = **Ready**) or ask Hawkeye chat to seed tasks.  
2. View the same board in Hawkeye.  
3. Update status in the task drawer (writes to Notion).  
4. Autopilot / overnight drain uses the same Build Queue.

Details: [docs/pm.md](docs/pm.md) · [docs/notion-setup.md](docs/notion-setup.md)

### 4. Local model (`coder-64k`)

```bash
./ollama/create_coder_64k.sh
# Override base if VRAM is tight:
# BASE_MODEL=qwen2.5-coder:3b ./ollama/create_coder_64k.sh
```

The Modelfile sets `num_ctx 65536` and a **Hawkeye** system prompt (BrownHawke engineering assistant). UI chat also injects Hawkeye identity + retrieved memory.

### 5. Vector memory + research

```bash
./bootstrap/05_use_data_ssd.sh
ollama pull nomic-embed-text
```

- Each UI chat turn is embedded and stored under `$AUTOCODE_DATA_ROOT/hawkeye/memory/`  
- Top-k memories are injected before the next reply  
- Optional `HAWKEYE_MEMORY_KEY` encrypts lines at rest  

Never commit `memories.jsonl` or sync personal memory into public Autocode.

Docs: [docs/memory.md](docs/memory.md) · [docs/research.md](docs/research.md)

Deep research (`HAWKEYE_RESEARCH_DEEP=1`, default) fetches top result pages so answers use page text, not just snippets. Say `deep research …` in chat.

### 5b. Email answering (optional)

Use Resend receiving on a **subdomain** (e.g. `agent.brownhawke.engineering`) so it does not fight Cloudflare Email Routing on the apex:

```bash
# .env
HAWKEYE_MAIL_ENABLED=1
RESEND_API_KEY=re_…
RESEND_WEBHOOK_SECRET=whsec_…
HAWKEYE_MAIL_FROM=hawkeye@agent.brownhawke.engineering
```

Webhook URL: `https://hawkeye.brownhawke.engineering/api/webhooks/resend`  
Approve drafts in the UI **Email inbox**. Guide: [docs/mail.md](docs/mail.md).

### 6. Boot auto-start

```bash
./scripts/install_hawkeye_autostart.sh
# enables linger + hawkeye-ui.service
# enables ollama when present
# enables hawkeye-tunnel.service when cloudflared + config/token exist

systemctl --user status hawkeye-ui.service
./scripts/install_hawkeye_autostart.sh --disable   # later
```

Overnight / continuous coding timers (separate):

```bash
# .env: AUTOCODE_AUTOPILOT_ENABLED=1  AUTOCODE_CONTINUOUS_ENABLED=1
./cron/install_autopilot_timers.sh
```

### 7. Public domain (Cloudflare Tunnel)

`hawkeye.brownhawke.engineering` only works when **both** are true:

1. DNS/tunnel route exists in Cloudflare  
2. Jetson is online with UI + `cloudflared`

```bash
# UI on loopback only (tunnel fronts it)
AUTOCODE_UI_HOST=127.0.0.1 ./scripts/ui.sh

cloudflared tunnel create hawkeye
cloudflared tunnel route dns hawkeye hawkeye.brownhawke.engineering
# Copy deploy/cloudflared.hawkeye.yml.example → ~/.cloudflared/config.yml
cloudflared tunnel run hawkeye

# Then re-run so tunnel unit is installed:
./scripts/install_hawkeye_autostart.sh
```

Until DNS exists, the hostname will not resolve — Jetson alone is not enough.

Private alternative (no public DNS): Tailscale + `./scripts/ui.sh --remote`.

Docs: [docs/hawkeye.md](docs/hawkeye.md) · [docs/email-routing.md](docs/email-routing.md)

---

## Day-to-day commands

| Goal | Command |
|------|---------|
| Open UI (local) | `./scripts/ui.sh` → http://127.0.0.1:8787/ |
| Open UI (Tailscale) | `./scripts/ui.sh --remote` |
| Health check | `./scripts/doctor.sh` |
| Status / pause | `./scripts/status.sh` · `./scripts/control.sh pause` |
| Supervised night | `./cron/overnight_run.sh --force` |
| One work cycle | `./cron/worker_run.sh --force` |
| Recreate coder model | `./ollama/create_coder_64k.sh` |

---

## Architecture (short)

```
You (phone/laptop)
  → hawkeye.brownhawke.engineering (Cloudflare Tunnel)
    → Hawkeye UI on Jetson :8787
         ├─ Notion boards (PM)
         ├─ Chat → Ollama coder-64k (+ vector memory + research)
         ├─ Escalate → Cursor / Grok webhooks
         └─ Autopilot → Hermes drains Ready Notion tasks
```

More: [docs/architecture.md](docs/architecture.md) · [docs/how-ai-talks.md](docs/how-ai-talks.md)

---

## Documentation index

| Doc | Topic |
|-----|--------|
| [START_HERE.md](START_HERE.md) | Kid-simple first run |
| [docs/hawkeye.md](docs/hawkeye.md) | Private deploy (login, domain, escalate) |
| [docs/jetson.md](docs/jetson.md) | Jetson / SSD / Ollama notes |
| [docs/go-live.md](docs/go-live.md) | Full go-live checklist |
| [docs/pm.md](docs/pm.md) | Notion-backed team PM UI |
| [docs/ui.md](docs/ui.md) | Dashboard + remote access |
| [docs/memory.md](docs/memory.md) | Vector memory |
| [docs/research.md](docs/research.md) | Deep web research |
| [docs/mail.md](docs/mail.md) | Email inbox + answer |
| [docs/accounts.md](docs/accounts.md) | Per-user connections, projects, DMs |
| [docs/security.md](docs/security.md) | Login, tunnel, memory privacy |
| [docs/notion-setup.md](docs/notion-setup.md) | Notion provision / seed |
| [docs/continuous.md](docs/continuous.md) | Always-on drain |
| [docs/remote-ops.md](docs/remote-ops.md) | Phone / Tailscale ops |
| [docs/email-routing.md](docs/email-routing.md) | brandon@ → Outlook |

Notion handoff (workspace): see **Hawkeye** hub → *Handoff — Hawkeye Cursor session*.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `Password authentication is not supported` / `Invalid username or token` | Used GitHub account password — paste a **PAT** as the password, or use `gh auth login` / SSH |
| `Permission denied` cloning to `/opt/hawkeye` | Need sudo ownership, **or** clone to `~/Hawkeye` instead |
| `syntax error near unexpected token '('` | Pasted a Markdown comment line (`# Recommended — …`) — paste only the `git` / `cd` / `./scripts/...` lines |
| `hawkeye.brownhawke.engineering` won’t load | DNS/tunnel not created yet, **or** Jetson/cloudflared offline |
| UI asks for login / rejects email | Must be `@brownhawke.engineering`; check `config/users.json` |
| Empty / sample board | Missing `NOTION_TOKEN` or integration not shared on the DB |
| Chat says local model unavailable | Start Ollama; run `./ollama/create_coder_64k.sh` |
| UI gone after reboot | `./scripts/install_hawkeye_autostart.sh` (+ `loginctl` linger) |
| Doctor FAILs | Fix listed items; re-run `./scripts/doctor.sh` |

```bash
systemctl --user status hawkeye-ui.service
systemctl --user status hawkeye-tunnel.service
curl -fsS http://127.0.0.1:11434/api/tags
curl -fsS http://127.0.0.1:8787/ | head
```

---

## Repo boundary

| Autocode (public) | Hawkeye (this repo) |
|-------------------|---------------------|
| Apache-2.0 coding autopilot | Proprietary BrownHawke product |
| Reusable by others | Your domain, login, memory, secrets |
| No personal transcripts | SSD vector memory stays here |

Do **not** merge Hawkeye-only secrets or personal branding into Autocode `main`.

---

## License

**Proprietary** — BrownHawke Engineering. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Upstream Autocode (Apache-2.0) attribution is preserved in `NOTICE` and `LICENSE.Apache-2.0`. Keep this repository **private**. Never commit `.env`, webhook URLs, plaintext passwords, or `memories.jsonl`.
