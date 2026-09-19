# WhatsApp (Cloud API)

Hawkeye talks to Brandon over **official WhatsApp Cloud API (Meta)** — same chat / escalate path as the UI, plus operator notifications when the Ready queue empties or a human is needed.

No WhatsApp Web scrapers. Twilio WhatsApp is **not** used (nothing in this repo was closer to Twilio; Cloud API matches the Connections + public webhook pattern already used for Resend).

## What you get

| Path | Behavior |
|------|----------|
| **Inbound text** | Meta POST → allowlist → `handle_chat` (local Ollama, then Cursor/Grok escalate) → reply on WhatsApp |
| **Queue empty** | Notify when a work cycle finds no Ready tasks, or Ready is drained |
| **Blocked** | Notify when a task is marked Blocked (overnight sink or UI status write) |
| **Needs human** | Notify on escalate-to-Human and when autopilot is paused (waiting on operator) |
| **Digest** | Optional end-of-cycle summary (`notify_rules` must include `digest`) |

UI chat is unchanged. WhatsApp keeps its own per-number history under `$AUTOCODE_DATA_ROOT/hawkeye/whatsapp/` (or `HAWKEYE_WHATSAPP_DIR`).

## Connections UI

**Account → Connections → WhatsApp (Cloud API)**

| Field | Secret? | Purpose |
|-------|---------|---------|
| `phone_number_id` | no | Meta Phone number ID |
| `access_token` | yes | Permanent system-user token (or long-lived) |
| `verify_token` | yes | Shared string you invent; Meta GET handshake must match |
| `app_secret` | yes | App secret — HMAC-SHA256 of the POST body (`X-Hub-Signature-256`) |
| `allowed_numbers` | no | E.164 allowlist, comma-separated (Brandon only for v1) |
| `notify_rules` | no | Default `queue_empty,blocked,human`. Add `digest` to opt in. |

The card shows a copyable **Webhook URL** (not a secret you type in):

`https://hawkeye.brownhawke.engineering/api/webhooks/whatsapp`

Machine `.env` is the fallback when the vault is empty (overnight / webhook has no browser session; it reads `HAWKEYE_AUTOPILOT_EMAIL` / Brandon).

Set `HAWKEYE_MEMORY_KEY` under **Account → Machine** before saving secrets.

## One-time Meta setup

1. Create a [Meta Business](https://business.facebook.com/) account and a Facebook app with **WhatsApp** product (Cloud API).
2. Add / claim the WhatsApp Business phone number. Copy **Phone number ID**.
3. Create a system user (or use the temporary test token, then exchange for a permanent token). Grant `whatsapp_business_messaging` + `whatsapp_business_management`. Copy the **access token**.
4. In the app → WhatsApp → Configuration → Webhook:
   - Callback URL: `https://hawkeye.brownhawke.engineering/api/webhooks/whatsapp`
   - Verify token: the same string you saved as `verify_token`
   - Subscribe to the `messages` field
5. Copy the app **App secret** into `app_secret` (required to verify POST signatures).
6. Allowlist Brandon’s WhatsApp number in E.164 (digits with country code, `+` optional), e.g. `15551234567`.
7. Restart the UI if you used `.env` instead of Connections (`systemctl --user restart hawkeye-ui`).

Cloudflare Tunnel already publishes the Hawkeye UI; no extra open ports.

### Test numbers vs production

Meta’s Cloud API sandbox can only message numbers you add as testers. Add Brandon as a tester, then send a first WhatsApp message **to** the business number so the 24-hour customer-care window opens.

## Security

Inbound WhatsApp is untrusted, same class as email.

| Control | Default |
|---------|---------|
| Signature | `X-Hub-Signature-256` required when `app_secret` is set (`HAWKEYE_WHATSAPP_REQUIRE_SIGNATURE=1`) |
| Allowlist | Empty `allowed_numbers` rejects **all** inbound and outbound |
| Owner vault | Chat runs as `HAWKEYE_WHATSAPP_USER` / `HAWKEYE_AUTOPILOT_EMAIL` / Brandon |
| No secrets in git | Tokens live in the encrypted Connections vault or `.env` |
| Dedup | `wamid` stored so Meta retries do not double-chat |

Do **not** process numbers that are not on the allowlist. Do not paste access tokens into chat, PRs, or Notion.

Kill switch: `HAWKEYE_WHATSAPP_ENABLED=0`.

## Notifications

Configurable defaults (Connections `notify_rules` or env):

| Rule | Env override | When |
|------|--------------|------|
| `queue_empty` | `HAWKEYE_WHATSAPP_NOTIFY_QUEUE_EMPTY` | No Ready tasks, or Ready drained |
| `blocked` | `HAWKEYE_WHATSAPP_NOTIFY_BLOCKED` | Status Blocked |
| `human` | `HAWKEYE_WHATSAPP_NOTIFY_HUMAN` | Escalate to Human, or pause / awaiting operator |
| `digest` | `HAWKEYE_WHATSAPP_NOTIFY_DIGEST` | End-of-cycle digest (off unless listed) |

Example:

```bash
HAWKEYE_WHATSAPP_NOTIFY_RULES=queue_empty,blocked,human
# HAWKEYE_WHATSAPP_NOTIFY_DIGEST=1
# HAWKEYE_WHATSAPP_NOTIFY_TO=15551234567   # subset of allowlist
```

Proactive notifies only work as **session text** inside Meta’s 24h window (after Brandon last messaged Hawkeye). For always-on business-initiated alerts, create an approved template and set:

```bash
HAWKEYE_WHATSAPP_NOTIFY_TEMPLATE=hawkeye_alert
HAWKEYE_WHATSAPP_NOTIFY_TEMPLATE_LANG=en_US
```

The template body should accept one text parameter (the alert). If the template send fails, Hawkeye falls back to session text.

## Env reference

```bash
# Optional kill switch (default on when token + phone id exist)
HAWKEYE_WHATSAPP_ENABLED=1

# Machine fallbacks (prefer Account → Connections)
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_ALLOWED_NUMBERS=          # Brandon E.164, comma-separated
HAWKEYE_WHATSAPP_NOTIFY_RULES=queue_empty,blocked,human
# HAWKEYE_WHATSAPP_USER=brandon@brownhawke.engineering
# HAWKEYE_WHATSAPP_DIR=
# HAWKEYE_WHATSAPP_GRAPH_VERSION=v21.0
# HAWKEYE_WHATSAPP_REQUIRE_SIGNATURE=1
# HAWKEYE_WHATSAPP_NOTIFY_DEDUP_SEC=60
```

## API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` | verify token | Meta handshake — returns challenge as `text/plain` |
| `POST` | `/api/webhooks/whatsapp` | `X-Hub-Signature-256` | Inbound messages |

Both paths are public (no Hawkeye login), the same way Resend is. The Cloudflare Tunnel must reach the UI on loopback `:8787`.

## Test plan

Unit (no Meta network):

```bash
python3 -m unittest tests.test_whatsapp tests.test_accounts_collab -v
```

Covered:

1. GET verify — matching token returns challenge; mismatch → 403
2. POST HMAC — valid `sha256=` accepts; bad / missing signature rejected
3. Parse Cloud API `entry[].changes[].value.messages[]` text (and ignore status-only webhooks)
4. Allowlist reject
5. Notify rules: queue empty / blocked / human on by default; digest off; env override
6. `send_text` / notify use mocked `urlopen` (no live Graph calls)

Manual (after Meta is wired):

1. Save Connections fields; copy webhook URL into Meta; click Verify
2. Text the business number from Brandon’s allowlisted phone — reply should match UI chat
3. Pause a work cycle from the UI — WhatsApp “waiting on you”
4. Drain Ready / mark a task Blocked — WhatsApp alert
5. Confirm a non-allowlisted number is ignored (200 to Meta, no chat)

UI chat on `https://hawkeye.brownhawke.engineering` must keep working after this change.
