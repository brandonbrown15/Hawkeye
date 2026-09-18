# Hawkeye accounts, connections, shared projects & DMs

Each `@brownhawke.engineering` login has **their own**:

1. **Profile** — first name, last name, employee number  
2. **Connections** — Cloudflare, Notion, GitHub, Cursor, Claude, ChatGPT/Codex, Grok, OpenRouter, Brave Search, Telegram (secrets encrypted per user; used at runtime for your session)  
3. **Machine** — Jetson-wide tunnel token, encryption key, GitHub auto-update (writes `.env`, restarts services)  
4. **Projects** — account-owned workspaces that can be shared with teammates  
5. **Messages** — direct messages between coworkers  

Do all of this from the **online UI** at `https://hawkeye.brownhawke.engineering` (or SSH/Tailscale to `:8787`). Machine `.env` remains a fallback for overnight autopilot when no per-user secret is set.

## Profile

On first sign-in (or **Account → Profile**), set:

- First name  
- Last name  
- Employee number (e.g. `BH-0042`)

Stored in `$AUTOCODE_DATA_ROOT/hawkeye/accounts/profiles.json` (or `state/hawkeye-accounts/` in dev).

## Connections (account-based)

**Account → Connections** stores secrets only for the signed-in email. Chat escalate, Notion boards, and Brave research prefer these secrets, then fall back to machine `.env`.

| Provider | Typical secret |
|----------|----------------|
| Cloudflare | API token (+ optional account id) |
| Notion | Integration / OAuth token |
| GitHub | PAT |
| Cursor | API key / webhook URL + token |
| Claude | Anthropic API key |
| ChatGPT / Codex | OpenAI API key (+ optional org id) |
| Grok Bot / xAI | Webhook URL + token and/or xAI API key |
| OpenRouter | API key |
| Brave Search | API key (else DuckDuckGo HTML) |
| Telegram | Bot token + chat id |

Encrypt at rest with `HAWKEYE_MEMORY_KEY` or dedicated `HAWKEYE_SECRETS_KEY` (set under **Account → Machine**). The UI never displays raw secrets after save.

## Machine (Jetson-wide)

**Account → Machine** (any configured work user by default; restrict with `HAWKEYE_ADMIN_EMAILS`):

| Setting | Effect |
|---------|--------|
| Cloudflare Tunnel install token | Writes `TUNNEL_TOKEN` to `.env`, reinstalls/restarts `hawkeye-tunnel.service` |
| `HAWKEYE_MEMORY_KEY` | Enables encryption for connections + vector memory |
| Auto-update branch | `HAWKEYE_UPDATE_BRANCH` (default: current git branch) |
| Pull every 5 min | `HAWKEYE_UPDATE_ENABLED` + `hawkeye-update.timer` |
| Force update now | Runs `hawkeye_self_update.sh --force` |

```bash
HAWKEYE_MEMORY_KEY=…long passphrase…
# optional override:
# HAWKEYE_SECRETS_KEY=…
# HAWKEYE_ACCOUNTS_DIR=/path/on/ssd/hawkeye/accounts
# HAWKEYE_ADMIN_EMAILS=brandon@brownhawke.engineering
HAWKEYE_UPDATE_ENABLED=1
# HAWKEYE_UPDATE_BRANCH=main   # omit to track current branch
```

## Shared projects

**Account → Projects** (and the **My projects** board tab):

- Create a project owned by you  
- Share with any coworker who already has a Hawkeye login (`set_work_user.py`)  
- Roles: `owner` | `editor` | `viewer`  

This is separate from Notion boards (`/api/projects`). Notion boards use your Connection Notion token (or machine `NOTION_TOKEN`); Hawkeye projects are membership-gated in-app.

## Direct messages

**Messages** in the header (or Account → Messages):

- Pick a coworker from the directory  
- Send DMs (same work domain only)  
- Unread badge on the Messages button  

## API (session + CSRF)

| Method | Path |
|--------|------|
| `GET`/`POST` | `/api/me` |
| `GET` | `/api/users` |
| `GET` | `/api/connections` |
| `POST` | `/api/connections/{provider}` |
| `GET`/`POST` | `/api/machine` |
| `GET`/`POST` | `/api/account/projects` |
| `POST` | `/api/account/projects/{id}/share` |
| `GET` | `/api/messages/threads` |
| `POST` | `/api/messages` |

## Security notes

- Never put PATs in `config/users.json`  
- Prefer encrypted storage (`HAWKEYE_MEMORY_KEY`) before production use  
- Share/DM targets must be allowlisted domain + existing Hawkeye users  
- Gitignore / keep `hawkeye/accounts/` off git and off public Autocode  
- Tunnel install token is machine-scoped (not per coworker)  
