#!/usr/bin/env bash
# Delegate a task to Cursor Cloud via webhook / Background Agent hook.
# Requires CURSOR_WEBHOOK_URL (or CURSOR_DELEGATE_URL). Fails honestly if unset.
#
# Env:
#   AUTOCODE_DELEGATE_PAYLOAD  path to JSON payload (required)
#   CURSOR_WEBHOOK_URL         POST target (required for success)
#   CURSOR_WEBHOOK_TOKEN       optional Bearer token
#   CURSOR_API_KEY             optional alt auth header
set -euo pipefail

PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
URL="${CURSOR_WEBHOOK_URL:-${CURSOR_DELEGATE_URL:-}}"
TOKEN="${CURSOR_WEBHOOK_TOKEN:-${CURSOR_API_KEY:-}}"

if [[ -z "$PAYLOAD" || ! -f "$PAYLOAD" ]]; then
  echo "FAIL: AUTOCODE_DELEGATE_PAYLOAD missing or not a file"
  exit 1
fi

if [[ -z "$URL" ]]; then
  echo "FAIL: CURSOR_WEBHOOK_URL unset — cannot delegate to Cursor Cloud"
  echo "Set CURSOR_WEBHOOK_URL in .env, or point AUTOCODE_CURSOR_DELEGATE_CMD at your launcher."
  echo "Payload saved at: $PAYLOAD"
  exit 1
fi

echo "POST Cursor webhook ← $PAYLOAD"
HDR=(-H "Content-Type: application/json" -H "User-Agent: Autocode-Jetson/1.0")
if [[ -n "$TOKEN" ]]; then
  HDR+=(-H "Authorization: Bearer ${TOKEN}")
fi

HTTP_CODE="$(curl -sS -o /tmp/autocode-cursor-delegate.out -w '%{http_code}' \
  -X POST "${HDR[@]}" \
  --data-binary @"$PAYLOAD" \
  --max-time "${AUTOCODE_DELEGATE_TIMEOUT_SEC:-120}" \
  "$URL")"

echo "HTTP $HTTP_CODE"
head -c 800 /tmp/autocode-cursor-delegate.out 2>/dev/null || true
echo

case "$HTTP_CODE" in
  2??) exit 0 ;;
  *)
    echo "FAIL: Cursor webhook returned HTTP $HTTP_CODE"
    exit 1
    ;;
esac
