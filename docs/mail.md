# Hawkeye email inbox (answer inbound mail)

Hawkeye can receive mail via **Resend inbound webhooks**, draft a reply with the local Jetson model, and send only after you approve (default).

Human `@brownhawke.engineering` → Outlook forwarding remains documented in [email-routing.md](email-routing.md). Agent answering uses a **separate receiving address** (recommended subdomain) so Cloudflare Routing and Resend MX do not conflict.

## Architecture

```
Sender → Resend (MX on agent subdomain) → POST /api/webhooks/resend
                                              ↓
                                    allowlist + sanitize
                                              ↓
                                    store + local draft
                                              ↓
                                    UI approve → Resend send
```

## Security (required)

Inbound email is untrusted. Defaults:

| Setting | Default | Meaning |
|---------|---------|---------|
| `HAWKEYE_MAIL_SECURITY` | `domain` | Allow `@brownhawke.engineering` (and optional exact list) |
| `HAWKEYE_MAIL_ALLOWED_SENDERS` | _(empty)_ | Exact allowlist (required when security=`strict`) |
| `HAWKEYE_MAIL_ALLOWED_DOMAINS` | login domain | Extra domains if needed |
| `HAWKEYE_MAIL_AUTO_SEND` | `0` | Never auto-send; approve in UI |
| `HAWKEYE_MAIL_AUTO_DRAFT` | `1` | Draft with local model on receive |
| `RESEND_WEBHOOK_SECRET` | _(required in prod)_ | Svix signature verify |

Rejected senders and prompt-injection / scam patterns are stored with `status=rejected` for audit.

## One-time Resend setup

1. Create a Resend account and API key → put in Jetson `.env` as `RESEND_API_KEY` (do not paste into chat).
2. Add receiving for a subdomain, e.g. `agent.brownhawke.engineering` (Enable Receiving + MX in Resend docs).
3. Create webhook: URL `https://hawkeye.brownhawke.engineering/api/webhooks/resend`, event `email.received`.
4. Copy the webhook signing secret → `RESEND_WEBHOOK_SECRET=whsec_…`
5. Set from-address for replies, e.g. `HAWKEYE_MAIL_FROM=hawkeye@agent.brownhawke.engineering`

```bash
# .env
HAWKEYE_MAIL_ENABLED=1
RESEND_API_KEY=re_…
RESEND_WEBHOOK_SECRET=whsec_…
HAWKEYE_MAIL_FROM=hawkeye@agent.brownhawke.engineering
HAWKEYE_MAIL_SECURITY=domain
HAWKEYE_MAIL_AUTO_DRAFT=1
HAWKEYE_MAIL_AUTO_SEND=0
```

Restart the UI (`systemctl --user restart hawkeye-ui` or `./scripts/ui.sh`).

## UI

Open the dashboard → **Email inbox**:

- **Draft reply** — local Ollama
- **Send reply** — Resend (confirm dialog)
- **Ignore** — mark done without sending

## API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/webhooks/resend` | Svix signature | Inbound from Resend |
| `GET` | `/api/mail` | session | List messages |
| `POST` | `/api/mail/inject` | session + CSRF | Manual test inject |
| `POST` | `/api/mail/{id}/draft` | session + CSRF | Draft |
| `POST` | `/api/mail/{id}/send` | session + CSRF | Send |
| `POST` | `/api/mail/{id}/ignore` | session + CSRF | Ignore |

Manual inject (dev):

```bash
curl -sS -X POST http://127.0.0.1:8787/api/mail/inject \
  -H "Content-Type: application/json" \
  -H "X-Autocode-Token: $TOKEN" \
  -d '{"from":"brandon@brownhawke.engineering","to":"hawkeye@agent.brownhawke.engineering","subject":"Ping","body":"Status on tunnel?","token":"'"$TOKEN"'"}'
```

## Storage

Messages live under `$AUTOCODE_DATA_ROOT/hawkeye/mail/inbox.jsonl` (or `HAWKEYE_MAIL_DIR`).

## Notes

- Replies use Resend sending DNS on the agent subdomain (separate from Outlook forwarding).
- Drafts may run deep web research when the email itself asks for a lookup.
- Keep `HAWKEYE_MAIL_AUTO_SEND=0` unless you fully trust the allowlist and have reviewed drafts.
