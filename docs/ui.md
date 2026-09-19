# Autocode local UI

Kid-simple dashboard that runs **on the Jetson** (or any Linux box).

```bash
./scripts/ui.sh
# open http://127.0.0.1:8787/
```

Keep it running across reboots (Hawkeye on Jetson):

```bash
./scripts/install_hawkeye_autostart.sh
# systemctl --user status hawkeye-ui.service
```

Overnight / continuous worker timers (separate from UI boot):

```bash
./cron/install_autopilot_timers.sh
```

## What it does

- Live phase / task / route / heartbeat (same as `./scripts/status.sh`)
- Pause · Resume · Abort · Skip task
- Ready checklist (Notion, Hermes, Ollama, GitHub, autopilot / continuous)
- **Run work cycle** — drain Ready Notion tasks now
- **Talk to Autocode** — chat with the local LLM; auto-escalates to a larger cloud model when needed
- Mock cycle for dry practice
- Tail of the latest log

The same dashboard works over Tailscale remote access — chat, controls, and status are identical on phone or laptop.

## Remote monitoring (phone / laptop)

### Option A — Tailscale (recommended)

Same private network as the Jetson, no public internet exposure:

```bash
# On Jetson
./bootstrap/04_install_tailscale.sh
sudo tailscale up
./scripts/ui.sh --remote
# note the http://100.x.y.z:8787/ URL printed
```

From your phone/laptop (also on Tailscale), open that URL.

Always-on:

```bash
# in .env
AUTOCODE_UI_REMOTE=1
./scripts/install_hawkeye_autostart.sh   # hawkeye-ui.service on boot
```

Optional: `tailscale serve` / `tailscale funnel` if you want HTTPS on your Tailnet.

### Option B — SSH tunnel (safest default)

```bash
ssh -L 8787:127.0.0.1:8787 jetson
# open http://127.0.0.1:8787/ on your laptop
```

### Option C — Public domain (Hawkeye private)

Canonical host: **`https://hawkeye.brownhawke.engineering`** (subdomain of BrownHawke.engineering).  
Use login + Cloudflare Tunnel. See **[hawkeye.md](hawkeye.md)**.

```bash
AUTOCODE_PRIVATE_MODE=1
AUTOCODE_PRODUCT_NAME=Hawkeye
AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering
AUTOCODE_UI_SECURE=1
# password hash from: python3 scripts/set_private_password.py
AUTOCODE_PERSONAL_LOCAL_ONLY=0   # keep Cursor/Grok escalate (or use UI Local only switch)
cloudflared tunnel route dns hawkeye hawkeye.brownhawke.engineering
```

Do **not** bind `0.0.0.0` on a public IP without a tunnel + login.

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `AUTOCODE_UI_HOST` | `127.0.0.1` | Bind address |
| `AUTOCODE_UI_PORT` | `8787` | Port |
| `AUTOCODE_UI_REMOTE` | `0` | `1` = prefer Tailscale IP / LAN bind |
| `AUTOCODE_PUBLIC_HOST` | `hawkeye.brownhawke.engineering` | Hawkeye public hostname |
| `AUTOCODE_UI_SECURE` | `0` | Force Secure session cookies |

Mutating actions require a session token injected into the page (CSRF guard).


## Talk to Hawkeye / Autocode

The dashboard chat box talks to the **local** Ollama model first (free all day on the Jetson). Board commands (`what's on the Hawkeye board?`, `show open P0/P1`, `mark HK-xx Done`, `add a Ready task: …`) are handled locally against Notion and skip Cursor/Grok. Details: [pm.md](pm.md).

1. You type an instruction (locally, Tailscale, or private domain after login).
2. Local model answers when it can (with **conversation history** + a short Hawkeye workspace brief — it already knows `https://github.com/brandonbrown15/Hawkeye`).
3. If it cannot (says `ESCALATE:`, stalls asking for a URL you already gave, or you ask for a full repo review), Hawkeye forwards to **Cursor Cloud Agents API → Grok Bot webhook**, then optional API keys.
4. Optional checkbox: seed useful follow-ups into the Notion Ready checklist.

Set `CURSOR_API_KEY` (Cursor Dashboard → API Keys) for premium Cursor handoff. Optional: `CURSOR_REPOSITORY` for coding agents, or `CURSOR_WEBHOOK_URL` for a custom bridge. Also optional: `GROK_BOT_WEBHOOK_URL`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or `XAI_API_KEY`.

Use the **Local only** switch in the dashboard header to force free Jetson Ollama for chat (no Cursor/Grok). The setting is **per signed-in account** (stored under that email in `state/hawkeye-runtime.json`), so `brandon@` and `mark@` can choose independently. It overrides `AUTOCODE_PERSONAL_LOCAL_ONLY` for that user until they flip it back.

Private personal product: **[hawkeye.md](hawkeye.md)**.
