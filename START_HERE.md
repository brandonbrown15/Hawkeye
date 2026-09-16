# START HERE

## One command

```bash
git clone https://github.com/brandonbrown15/Autocode.git
cd Autocode
./start
```

Answer a few questions. Wait. Done.

---

## What you need before `./start`

1. **GitHub account**  
   Easy path: token at https://github.com/settings/tokens?type=beta  
   (Contents + Pull requests = Read and write)

2. **Notion account** (free is fine) — pick one:

   **A) Browser sign-in (like a plugin)** — best after one-time setup  
   - Create a **Public** integration: https://www.notion.so/my-integrations  
   - Redirect URI: `http://127.0.0.1:8765/callback`  
   - Put `NOTION_OAUTH_CLIENT_ID` + `NOTION_OAUTH_CLIENT_SECRET` in `.env`  
   - Then `./start` → choose browser sign-in (or run `./scripts/connect_notion.sh`)

   **B) Paste a secret** (also fine)  
   - Internal integration → copy Secret when `./start` asks

   Either way, also: blank page **Autocode Hub** → **••• → Connections → Autocode** → paste page link

3. **This computer on** (Jetson or Linux)

Optional: big SSD (4TB). `./start` will try to use it automatically.

---

## After setup

| Do this | Command |
|---------|---------|
| Open the dashboard | `./scripts/ui.sh` → http://127.0.0.1:8787/ |
| Remote phone view | `./scripts/ui.sh --remote` (Tailscale) |
| Project autopilot until finished | set `AUTOCODE_CONTINUOUS_ENABLED=1` + `AUTOCODE_DRAIN_UNTIL_EMPTY=1` + `./cron/install_autopilot_timers.sh` |
| See if it is healthy | `./scripts/doctor.sh` |
| See what it is doing | `./scripts/status.sh` |
| Pause it | `./scripts/control.sh pause` |
| Add work | Notion → Build Queue → Status = **Ready** |

Keep the first tasks tiny (fix typos, small docs). More: [docs/continuous.md](docs/continuous.md) · [docs/ui.md](docs/ui.md)

---

## Stuck?

```bash
./scripts/doctor.sh
```

Read the **FAIL** lines. Fix those. Run `./start` again.

More detail: [docs/go-live.md](docs/go-live.md)
