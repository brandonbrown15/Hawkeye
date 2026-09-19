# Cloudflare Email Routing — BrownHawke work addresses

Hawkeye login is locked to `@brownhawke.engineering`. Set up real mailboxes with
Cloudflare Email Routing (free) so those addresses also receive mail.

## Goal

| Address | Forwards to |
|---------|-------------|
| `brandon@brownhawke.engineering` | `brandonabrown15@outlook.com` |

Add more teammates the same way (destination = their personal inbox).

## One-time setup (dashboard)

DNS for `brownhawke.engineering` must already be on Cloudflare.

1. Open [Email Routing](https://dash.cloudflare.com/?to=/:account/email-service/routing) and select **brownhawke.engineering**.
2. Enable **Email Routing** if prompted (Cloudflare will add MX / SPF / DKIM / DMARC records).
3. **Destination Addresses** → add `brandonabrown15@outlook.com` → check Outlook and click **Verify email address**.
4. **Routing Rules** → **Create routing rule**:
   - Email pattern: `brandon` @ `brownhawke.engineering`
   - Action: Send to an email
   - Destination: `brandonabrown15@outlook.com`
5. Save. Send a test message to `brandon@brownhawke.engineering` from a different account.

## Team pattern

Repeat destination + rule for each engineer, e.g. `alex@brownhawke.engineering` → their inbox.  
Hawkeye accounts are separate: `./scripts/hawkeye accounts set-password --email alex@brownhawke.engineering` ([login.md](login.md)).

## API (optional)

If you have a Cloudflare API token with Email Routing edit permission:

```bash
# Destination (then verify via Outlook link)
curl -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/email/routing/addresses" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"email":"brandonabrown15@outlook.com"}'

# Custom address / rule (zone must have Email Routing enabled)
curl -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/email/routing/rules" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "brandon",
    "enabled": true,
    "matchers": [{"type":"literal","field":"to","value":"brandon@brownhawke.engineering"}],
    "actions": [{"type":"forward","value":["brandonabrown15@outlook.com"]}]
  }'
```

This cloud agent does **not** have Cloudflare credentials, so routing must be created in the dashboard (or with your token locally).

## Notes

- Replies still send from Outlook, not from `@brownhawke.engineering` (Email Routing is receive/forward only).
- Catch-all is optional; prefer explicit rules for the eng team.
- For **Hawkeye to answer mail with the local model**, use Resend receiving on a subdomain — see [mail.md](mail.md). Do not point the apex MX at both Cloudflare Routing and Resend.
