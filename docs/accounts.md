# Hawkeye accounts, connections, shared projects & DMs

Each `@brownhawke.engineering` login has **their own**:

1. **Profile** — first name, last name, employee number  
2. **Connections** — Cloudflare, Notion, GitHub, Cursor, Claude, ChatGPT/Codex (secrets encrypted per user)  
3. **Projects** — account-owned workspaces that can be shared with teammates  
4. **Messages** — direct messages between coworkers  

Machine `.env` tokens still power overnight autopilot. UI connections are per signed-in person.

## Profile

On first sign-in (or **Account → Profile**), set:

- First name  
- Last name  
- Employee number (e.g. `BH-0042`)

Stored in `$AUTOCODE_DATA_ROOT/hawkeye/accounts/profiles.json` (or `state/hawkeye-accounts/` in dev).

## Connections (account-based)

**Account → Connections** stores secrets only for the signed-in email.

| Provider | Typical secret |
|----------|----------------|
| Cloudflare | API token (+ optional account id) |
| Notion | Integration / OAuth token |
| GitHub | PAT |
| Cursor | API key / webhook URL + token |
| Claude | Anthropic API key |
| ChatGPT / Codex | OpenAI API key (+ optional org id) |

Encrypt at rest with `HAWKEYE_MEMORY_KEY` or dedicated `HAWKEYE_SECRETS_KEY`. The UI never displays raw secrets after save.

```bash
HAWKEYE_MEMORY_KEY=…long passphrase…
# optional override:
# HAWKEYE_SECRETS_KEY=…
# HAWKEYE_ACCOUNTS_DIR=/path/on/ssd/hawkeye/accounts
```

## Shared projects

**Account → Projects** (and the **My projects** board tab):

- Create a project owned by you  
- Share with any coworker who already has a Hawkeye login (`set_work_user.py`)  
- Roles: `owner` | `editor` | `viewer`  

This is separate from Notion boards (`/api/projects`). Notion boards remain team-wide via the machine Notion token; Hawkeye projects are membership-gated in-app.

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
| `GET`/`POST` | `/api/account/projects` |
| `POST` | `/api/account/projects/{id}/share` |
| `GET` | `/api/messages/threads` |
| `POST` | `/api/messages` |

## Security notes

- Never put PATs in `config/users.json`  
- Prefer encrypted storage (`HAWKEYE_MEMORY_KEY`) before production use  
- Share/DM targets must be allowlisted domain + existing Hawkeye users  
- Gitignore / keep `hawkeye/accounts/` off git and off public Autocode  
