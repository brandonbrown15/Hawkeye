# Hawkeye — private personal deploy

Hawkeye is your **private** fork of Autocode:

- **Free local LLM** (Ollama on Jetson) for all-day phone/laptop use  
- **Cursor + Grok Bot** escalate when the ask is too strenuous  
- **Login** on the UI before anything useful loads  
- **Your domain** via Cloudflare Tunnel (or Tailscale)

Open-source Autocode stays a separate public repo. Do not merge Hawkeye-only secrets or personal branding into Autocode `main`.

## 1. Create the private GitHub repo

The cloud agent cannot create private repos with the current GitHub token. On GitHub:

1. Open **https://github.com/brandonbrown15/Hawkeye** (private).  
2. From this tree (once the Cursor GitHub App can access that repo):

```bash
chmod +x scripts/publish_hawkeye_private.sh
./scripts/publish_hawkeye_private.sh https://github.com/brandonbrown15/Hawkeye.git
```

## 2. Turn on login + product name

Work emails only (`@brownhawke.engineering`). Brandon is seeded in `config/users.json`.
Add teammates:

```bash
python3 scripts/set_work_user.py --email alex@brownhawke.engineering
```

`.env`:

```bash
AUTOCODE_PRODUCT_NAME=Hawkeye
AUTOCODE_PRIVATE_MODE=1
HAWKEYE_ALLOWED_EMAIL_DOMAIN=brownhawke.engineering
HAWKEYE_USERS_FILE=config/users.json
AUTOCODE_PERSONAL_LOCAL_ONLY=0
AUTOCODE_LOCAL_ONLY=0
AUTOCODE_COST_PROFILE=cursor-grok
AUTOCODE_CLOUD_PREFERENCE=cursor
CURSOR_WEBHOOK_URL=https://…
GROK_BOT_WEBHOOK_URL=https://…
AUTOCODE_UI_REMOTE=1
AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering
AUTOCODE_UI_SECURE=1
```

Set up `brandon@brownhawke.engineering` → Outlook forwarding: [email-routing.md](email-routing.md).

## 3. Domain — `hawkeye.brownhawke.engineering`

You already own **BrownHawke.engineering**. Point Hawkeye at the subdomain:

**Canonical URL:** `https://hawkeye.brownhawke.engineering`

Use a **Cloudflare Tunnel** to the Jetson UI on loopback (HTTPS, no open ports):

```bash
# On Jetson — UI on loopback only
AUTOCODE_UI_HOST=127.0.0.1 ./scripts/ui.sh

# One-time tunnel + DNS (Cloudflare must manage DNS for brownhawke.engineering,
# or create a CNAME at your registrar to the tunnel target Cloudflare prints)
cloudflared tunnel create hawkeye
cloudflared tunnel route dns hawkeye hawkeye.brownhawke.engineering
```

Example `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /home/YOU/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: hawkeye.brownhawke.engineering
    service: http://127.0.0.1:8787
  - service: http_status:404
```

```bash
cloudflared tunnel run hawkeye
```

In `.env` on the Jetson:

```bash
AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering
AUTOCODE_UI_SECURE=1
```

`AUTOCODE_UI_SECURE=1` (or `X-Forwarded-Proto: https` from the tunnel) makes the login cookie `Secure`.

Alternative: Tailscale only (`./scripts/ui.sh --remote`) — no public hostname required.

## 4. Auto-start on Jetson boot

So Hawkeye comes back when the box powers on:

```bash
./scripts/install_hawkeye_autostart.sh
# enables hawkeye-ui.service (+ linger so it starts without a login)
# enables ollama.service when present
# enables hawkeye-tunnel.service when cloudflared + config/token exist
```

`bootstrap_jetson.sh` runs this automatically (skip with `SKIP_AUTOSTART=1`).

Check / disable:

```bash
systemctl --user status hawkeye-ui.service
./scripts/install_hawkeye_autostart.sh --disable
```

## 5. Phone use

1. Open `https://hawkeye.brownhawke.engineering`  
2. Sign in  
3. Chat hits **local** Ollama first  
4. Hard asks POST to **Cursor** then **Grok Bot** (or reverse if `AUTOCODE_CLOUD_PREFERENCE=grok`)

## 6. Vector memory + web research

```bash
./bootstrap/05_use_data_ssd.sh   # creates $AUTOCODE_DATA_ROOT/hawkeye/memory
ollama pull nomic-embed-text     # better embeddings
# optional:
# HAWKEYE_MEMORY_KEY=… long passphrase …
# BRAVE_SEARCH_API_KEY=…
```

- Memory docs: [memory.md](memory.md)  
- Research docs: [research.md](research.md)  
- Security baseline: [security.md](security.md)  

Same Notion autopilot / continuous drain as Autocode when you enable those flags.

## Env reference

| Variable | Default (Hawkeye) | Meaning |
|----------|-------------------|---------|
| `AUTOCODE_PRODUCT_NAME` | `Hawkeye` | Brand in UI |
| `AUTOCODE_PRIVATE_MODE` | `1` | Require login |
| `AUTOCODE_PRIVATE_USER` | `brown` | Login username |
| `AUTOCODE_PRIVATE_PASSWORD_HASH` | _(required)_ | From `set_private_password.py` |
| `AUTOCODE_PUBLIC_HOST` | `hawkeye.brownhawke.engineering` | Public hostname (docs / cookie hints) |
| `AUTOCODE_PERSONAL_LOCAL_ONLY` | `0` | `1` = never call Cursor/Grok/APIs (UI **Local only** switch also writes `state/hawkeye-runtime.json`) |
| `AUTOCODE_LOCAL_ONLY` | `0` | Task router: allow cloud delegates |
| `HAWKEYE_RUNTIME_FILE` | `state/hawkeye-runtime.json` | Persisted UI toggles (local-only, etc.) |
| `CURSOR_WEBHOOK_URL` | | Premium escalate |
| `GROK_BOT_WEBHOOK_URL` | | Premium escalate |
| `AUTOCODE_UI_SECURE` | `0` | Force Secure cookies |
