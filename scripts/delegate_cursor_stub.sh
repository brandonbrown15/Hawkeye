#!/usr/bin/env bash
# Example / demo Cursor handoff. Always exits 0 after printing the payload.
# For live nights use ./scripts/delegate_cursor.sh + CURSOR_WEBHOOK_URL.
set -euo pipefail

PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
if [[ -z "$PAYLOAD" || ! -f "$PAYLOAD" ]]; then
  echo "AUTOCODE_DELEGATE_PAYLOAD missing"
  exit 1
fi

echo "(stub) Would delegate to Cursor Cloud with payload:"
head -c 800 "$PAYLOAD"
echo
echo "(stub) Live: set CURSOR_WEBHOOK_URL and AUTOCODE_CURSOR_DELEGATE_CMD=./scripts/delegate_cursor.sh"
exit 0
