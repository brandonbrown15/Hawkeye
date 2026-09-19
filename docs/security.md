# Security

Hawkeye / Autocode is designed so the **public Autocode git repo never holds secrets**. The private Hawkeye repo still must not commit `.env`, password hashes, memory files, or webhook URLs.

## What belongs in git

- Scripts, Modelfiles, docs, `.env.example`
- Placeholder Notion schema (`notion/ids.example.yaml`)
- Sample Cloudflare Tunnel config (`deploy/cloudflared.hawkeye.yml.example`)

## What must stay local

| File / value | Why |
|--------------|-----|
| `.env` | Tokens, chat IDs, API keys, password hash, memory key |
| `notion/ids.yaml` | Your private database IDs (optional) |
| `~/.hermes/`, SSH keys, `gh` auth | Machine credentials |
| `logs/`, `state/` | Runtime output |
| `$AUTOCODE_DATA_ROOT/hawkeye/memory/` | Personal vector memory (never Autocode) |
| Cloudflare Tunnel credentials JSON | Domain exposure credentials |

## Hawkeye baseline (login + tunnel + memory)

### 1. Login (work email only)

Only `@brownhawke.engineering` addresses can sign in. Password hashes live in
`config/users.json` (never commit plaintext passwords).

```bash
./scripts/hawkeye accounts set-password --email teammate@brownhawke.engineering
# .env:
AUTOCODE_PRIVATE_MODE=1
HAWKEYE_ALLOWED_EMAIL_DOMAIN=brownhawke.engineering
HAWKEYE_USERS_FILE=config/users.json
AUTOCODE_UI_SECURE=1
AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering
```

Mail forwarding for those addresses: [email-routing.md](email-routing.md).

### 2. Tunnel-only exposure

Do **not** publish port 8787 on the LAN/WAN. Terminate TLS at Cloudflare Tunnel:

```bash
AUTOCODE_UI_HOST=127.0.0.1 ./scripts/ui.sh
cloudflared tunnel run hawkeye
```

`X-Forwarded-Proto: https` (or `AUTOCODE_UI_SECURE=1`) marks the session cookie `Secure`.

### 3. Memory at-rest encryption plan

| Phase | Control |
|-------|---------|
| **Now** | Memory lives only under `$AUTOCODE_DATA_ROOT/hawkeye/memory` on the Jetson SSD. `.gitignore` excludes `state/` and never tracks `memories.jsonl`. |
| **Recommended** | Set `HAWKEYE_MEMORY_KEY` to a long passphrase (or 32+ hex bytes). Each JSONL line is encrypted with HMAC-SHA256 integrity + SHA-256 keystream (stdlib-only). Without the key, records are unreadable. |
| **Hardening** | Full-disk encryption on the 4TB SSD (LUKS); store `HAWKEYE_MEMORY_KEY` in a root-owned file `0600` outside the repo (e.g. `/etc/hawkeye/memory.key`) and export it from the systemd unit. |
| **Upgrade path** | Optional: wrap lines with `cryptography.Fernet` or `age` once those packages are pinned in a private Jetson venv. Keep the same `HAWKEYE_MEMORY_DIR` layout. |
| **Retention** | Operator-controlled; prune `memories.jsonl` or rotate the key (rewriting the file) when offboarding devices. |
| **Boundary** | Personal memory **never** lands in public Autocode PRs, issues, or docs. |

### 4. No secrets in public Autocode

- Hawkeye branding, proprietary `LICENSE`, login, memory, and research stay in **brandonbrown15/Hawkeye** (private).
- Autocode `main` remains Apache-2.0 OSS without personal domains, password hashes, or SSD memory paths required to run.
- Holding seed on Autocode PR #3 must **not** be merged to Autocode `main`.

## Rules for operators and agents

1. Never commit `.env` or paste tokens into PRs / public Notion pages.
2. Prefer `gh auth login` or deploy keys over long-lived PATs in files.
3. Keep Ollama on loopback (`127.0.0.1:11434`) unless you intentionally protect it.
4. Autopilot must not invent, rotate, or exfiltrate secrets.
5. Paid cloud fallbacks leave the machine — disable them for sensitive workspaces.
6. **Hawkeye private UI:** strong password hash, tunnel-only UI, encrypted memory when possible.
7. Never copy `hawkeye/memory/` into Autocode or any public gist.

## If a secret is leaked

1. Rotate the token at the provider immediately.
2. Purge it from git history if it was committed.
3. Rotate `HAWKEYE_MEMORY_KEY` and `AUTOCODE_PRIVATE_PASSWORD_HASH`.
4. Open a GitHub security advisory if the leak affected published Autocode releases.
