#!/usr/bin/env bash
# Delegate a task to your Grok Bot (Telegram / webhook / SuperGrok bridge).
# Requires GROK_BOT_WEBHOOK_URL (or GROK_DELEGATE_URL). Fails honestly if unset.
#
# Env:
#   AUTOCODE_DELEGATE_PAYLOAD  path to JSON payload (required)
#   GROK_BOT_WEBHOOK_URL       POST target (required for success)
#   GROK_BOT_WEBHOOK_TOKEN     optional Bearer token
set -euo pipefail

PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
URL="${GROK_BOT_WEBHOOK_URL:-${GROK_DELEGATE_URL:-}}"
TOKEN="${GROK_BOT_WEBHOOK_TOKEN:-}"

if [[ -z "$PAYLOAD" || ! -f "$PAYLOAD" ]]; then
  echo "FAIL: AUTOCODE_DELEGATE_PAYLOAD missing or not a file"
  exit 1
fi

if [[ -z "$URL" ]]; then
  echo "FAIL: GROK_BOT_WEBHOOK_URL unset — cannot delegate to Grok Bot"
  echo "Set GROK_BOT_WEBHOOK_URL in .env, or point AUTOCODE_GROK_DELEGATE_CMD at your Bot."
  echo "Payload saved at: $PAYLOAD"
  exit 1
fi

echo "POST Grok Bot webhook ← $PAYLOAD"
HDR=(-H "Content-Type: application/json" -H "User-Agent: Autocode-Jetson/1.0")
if [[ -n "$TOKEN" ]]; then
  HDR+=(-H "Authorization: Bearer ${TOKEN}")
fi

HTTP_CODE="$(curl -sS -o /tmp/autocode-grok-delegate.out -w '%{http_code}' \
  -X POST "${HDR[@]}" \
  --data-binary @"$PAYLOAD" \
  --max-time "${AUTOCODE_DELEGATE_TIMEOUT_SEC:-120}" \
  "$URL")"

echo "HTTP $HTTP_CODE"
head -c 800 /tmp/autocode-grok-delegate.out 2>/dev/null || true
echo

case "$HTTP_CODE" in
  2??) exit 0 ;;
  *)
    echo "FAIL: Grok Bot webhook returned HTTP $HTTP_CODE"
    exit 1
    ;;
esac
