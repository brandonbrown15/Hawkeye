#!/usr/bin/env bash
# Example / demo Grok Bot handoff. Always exits 0 after printing the payload.
# For live nights use ./scripts/delegate_grok.sh + GROK_BOT_WEBHOOK_URL.
set -euo pipefail

PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
if [[ -z "$PAYLOAD" || ! -f "$PAYLOAD" ]]; then
  echo "AUTOCODE_DELEGATE_PAYLOAD missing"
  exit 1
fi

echo "(stub) Would delegate to Grok Bot with payload:"
head -c 800 "$PAYLOAD"
echo
echo "(stub) Live: set GROK_BOT_WEBHOOK_URL and AUTOCODE_GROK_DELEGATE_CMD=./scripts/delegate_grok.sh"
exit 0
