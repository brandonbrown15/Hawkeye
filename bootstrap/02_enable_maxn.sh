#!/usr/bin/env bash
# Enable MAXN / MAXN_SUPER power mode when available (Jetson).
set -euo pipefail

if ! command -v nvpmodel >/dev/null 2>&1; then
  echo "nvpmodel not found — skip (not a Jetson or JetPack tools missing)"
  exit 0
fi

echo "== nvpmodel modes =="
nvpmodel -q 2>/dev/null || true

# Prefer MAXN_SUPER, then MAXN, else leave unchanged.
MODE_ID=""
if nvpmodel -p 2>/dev/null | grep -qi 'MAXN_SUPER'; then
  MODE_ID="$(nvpmodel -p 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /MAXN_SUPER/ {print $1; exit}')"
elif nvpmodel -p 2>/dev/null | grep -qi 'MAXN'; then
  MODE_ID="$(nvpmodel -p 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /MAXN/ && $0 !~ /SUPER/ {print $1; exit}')"
fi

if [[ -z "$MODE_ID" ]]; then
  echo "Could not auto-detect MAXN mode id. Set manually: sudo nvpmodel -m <id>"
  exit 0
fi

echo "Setting nvpmodel -m $MODE_ID"
sudo nvpmodel -m "$MODE_ID"
nvpmodel -q 2>/dev/null || true
echo "Done."
