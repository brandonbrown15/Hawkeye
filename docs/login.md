# Hawkeye login path and second-user runbook

Canonical URL: `https://hawkeye.brownhawke.engineering`

This is the operator runbook for **why logins fail** and **how to add Mark (or any teammate)** on the Jetson **without putting passwords in git**.

## Two gates (do not mix them up)

```text
Browser
  → Cloudflare edge (HTTPS)
      → Cloudflare Tunnel (cloudflared on the Jetson)
          → Hawkeye UI 127.0.0.1:8787
              → GET /  (no session) → 302 /login
              → POST /api/login  {email, password}
                  → Set-Cookie: hawkeye_session=…; HttpOnly; SameSite=Lax; Secure
              → in-memory session map (lost on hawkeye-ui restart)
```

| Gate | What it is | What it is not |
|------|------------|----------------|
| **Cloudflare Access** (Zero Trust app policy) | Optional extra login (email PIN / IdP) *in front of* Hawkeye. Browser sees a Cloudflare page, not the navy Hawkeye card. | **Not enabled** on `hawkeye.brownhawke.engineering` as of 2026-09-19 (no `Cf-Access-*` headers; `/api/auth` returns `cloudflare_access: false`). |
| **Hawkeye account** | Work email + password stored as a PBKDF2 hash in `config/users.json` on the Jetson. | Not Outlook, not GitHub, not the Cloudflare dashboard password. |

If someone is stuck on a **Cloudflare Access** page, allowlist their address in Zero Trust. That does **not** create a Hawkeye password.

## Failure modes (what users actually see)

Probed against production 2026-09-19 (`/api/build` → `rev=6f54368`, `root=/home/shaggy/Hawkeye`).

| Symptom | Likely cause | How we tell |
|---------|--------------|-------------|
| Navy Hawkeye card; “Wrong password for mark@…” | Account **exists**; secret does not match the hash | `POST /api/login` → `code=wrong_password`. **This is Mark’s current live state.** The hash was added in PR #12; the plaintext was never stored (correct) so he cannot guess it. |
| “No Hawkeye account for …” | Email missing from the users file the *running* UI loaded | `code=unknown_account` |
| “Only @brownhawke.engineering …” | Gmail / Outlook / typo domain | `code=bad_domain` |
| “Email and password required” | Empty password (autofill race) | `code=empty` — use **Show** on the form |
| Sign-in 200 then bounce back to `/login` with no error | Browser dropped `Set-Cookie` | New UI checks `/api/auth` after login and shows `cookie_not_stored`. Usually: HTTP instead of HTTPS, IP instead of `hawkeye.brownhawke.engineering`, or `Secure` cookie on loopback. |
| Cloudflare Access / PIN page | Access policy in front of the tunnel | `code=access_blocked` (HTML/403/Location contains Cloudflare Access) |
| 502 / blank | Tunnel or `hawkeye-ui.service` down | `code=tunnel_down` |
| HEAD/health 501 (fixed here) | `BaseHTTPRequestHandler` had no `do_HEAD` | Cloudflare or monitors sending HEAD |
| Reset script “worked” but login still wrong | UI used to cache `users.json` forever | File mtime is now re-read on each login. Restart if needed: `systemctl --user restart hawkeye-ui.service` |
| CSRF `bad token` *after* a successful login | Missing `X-Autocode-Token` on mutating API calls — **not** the login POST | Login is public. Dashboard JS already sends the CSRF token. |
| Case / spaces in email | Previously easy to mistype | Email is trimmed + lowercased; `mark` → `mark@brownhawke.engineering` |

Sessions live **only in the UI process memory**. Two `hawkeye-ui` processes (split checkout) = cookie from A is invalid on B. Check `/api/build` `pid` + `root`.

## Add or reset Mark on the Jetson (no password in git)

SSH or sit at the Orin (HDMI / existing session). **Do not** put the password on the command line if you can avoid it (shell history).

```bash
cd ~/Hawkeye          # or wherever the clone lives
git pull origin main  # so this CLI exists

# Create or reset — prompts twice, writes a hash only
./scripts/hawkeye accounts set-password --email mark@brownhawke.engineering

# Confirm the email is present (hashes are never printed)
./scripts/hawkeye accounts list

# Optional: Mark types the password himself to verify
./scripts/hawkeye accounts check --email mark@brownhawke.engineering

# Only if the UI still serves the old hash
systemctl --user restart hawkeye-ui.service
```

Equivalent legacy command (same code):

```bash
python3 scripts/set_work_user.py --email mark@brownhawke.engineering
```

Tell Mark the password **out of band** (in person / existing DM). Then he signs in at `https://hawkeye.brownhawke.engineering/login`.

The **public login page and unauthenticated API hints** must not show Jetson commands, `systemctl`, or filesystem paths. Teammates are pointed at `enquire@brownhawke.engineering` or Brandon. Keep this runbook for operators only.

First-time profile fields (name, employee #) are optional on that form; he can also set them under **Account → Profile**.

## Cookie / tunnel notes

- Tunnel must forward `X-Forwarded-Proto: https` (cloudflared does). The UI then sets `Secure` on `hawkeye_session`.
- `AUTOCODE_UI_SECURE=1` must **not** force `Secure` on `http://127.0.0.1` — browsers drop it and login looks like a bad password.
- Logout now clears the cookie with the same `Secure` flag so the session actually dies on HTTPS.
- `SameSite=Lax` is correct for a first-party form + `fetch(..., credentials: "same-origin")` on the same host.

## Related

- [accounts.md](accounts.md) — profiles, connections, projects, DMs
- [hawkeye.md](hawkeye.md) — tunnel + `.env`
- [security.md](security.md) — never commit plaintext passwords
