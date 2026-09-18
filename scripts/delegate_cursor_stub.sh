#!/usr/bin/env bash
# Stub Cursor delegate — prints payload path and exits 0 for dry runs.
# For live nights use CURSOR_API_KEY + ./scripts/delegate_cursor.sh
# (or CURSOR_WEBHOOK_URL for a custom bridge).
set -euo pipefail
PAYLOAD="${AUTOCODE_DELEGATE_PAYLOAD:-}"
echo "(stub) Cursor escalate payload: ${PAYLOAD:-<none>}"
echo "(stub) Live: set CURSOR_API_KEY (Dashboard → API Keys) and AUTOCODE_CURSOR_DELEGATE_CMD=./scripts/delegate_cursor.sh"
exit 0
