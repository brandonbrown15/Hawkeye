#!/usr/bin/env bash
# Delegate a task to Cursor Cloud Agents.
#
# Preference order:
#   1. CURSOR_API_KEY → Cloud Agents API via integrations.cursor_cloud
#   2. CURSOR_WEBHOOK_URL → custom inbound bridge (legacy)
#
# Env:
#   AUTOCODE_DELEGATE_PAYLOAD  path to JSON payload (required)
#   CURSOR_API_KEY             Cursor Dashboard API key (preferred)
#   CURSOR_REPOSITORY          optional https://github.com/org/repo
#   CURSOR_WEBHOOK_URL         optional custom bridge POST target
#   CURSOR_WEBHOOK_TOKEN       optional Bearer for webhook bridge
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
URL="${CURSOR_WEBHOOK_URL:-${CURSOR_DELEGATE_URL:-}}"
TOKEN="${CURSOR_WEBHOOK_TOKEN:-}"
API_KEY="${CURSOR_API_KEY:-}"

if [[ -z "$PAYLOAD" || ! -f "$PAYLOAD" ]]; then
  echo "FAIL: AUTOCODE_DELEGATE_PAYLOAD missing or not a file"
  exit 1
fi

if [[ -n "$API_KEY" ]]; then
  echo "Launch Cursor Cloud Agent via API ← $PAYLOAD"
  cd "$ROOT"
  export CURSOR_API_KEY AUTOCODE_DELEGATE_PAYLOAD="$PAYLOAD"
  # Prefer repo-root on PYTHONPATH so `integrations` imports cleanly.
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
  python3 -m integrations.cursor_cloud --payload "$PAYLOAD"
  exit $?
fi

if [[ -z "$URL" ]]; then
  echo "FAIL: set CURSOR_API_KEY (Dashboard → API Keys) or CURSOR_WEBHOOK_URL"
  echo "Payload saved at: $PAYLOAD"
  exit 1
fi

echo "POST Cursor webhook bridge ← $PAYLOAD"
HDR=(-H "Content-Type: application/json" -H "User-Agent: Autocode-Jetson/1.0")
if [[ -n "$TOKEN" ]]; then
  HDR+=(-H "Authorization: Bearer ${TOKEN}")
elif [[ -n "${CURSOR_API_KEY:-}" ]]; then
  HDR+=(-H "Authorization: Bearer ${CURSOR_API_KEY}")
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
