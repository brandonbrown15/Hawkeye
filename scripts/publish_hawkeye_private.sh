#!/usr/bin/env bash
# Push this working tree to a NEW private GitHub repo named Hawkeye.
# Autocode (public) stays separate — this script only adds a "hawkeye" remote.
#
# Prerequisites (you must do these — the cloud agent token cannot create private repos):
#   1. On GitHub: New repository → name Hawkeye → Private → empty (no README)
#   2. Grant this machine push access (PAT with repo scope, or SSH)
#
# Usage:
#   ./scripts/publish_hawkeye_private.sh
#   ./scripts/publish_hawkeye_private.sh git@github.com:YOU/Hawkeye.git
#   HAWKEYE_REMOTE_URL=https://github.com/YOU/Hawkeye.git ./scripts/publish_hawkeye_private.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL="${1:-${HAWKEYE_REMOTE_URL:-https://github.com/brandonbrown15/Hawkeye.git}}"

echo "Hawkeye private remote → $URL"
if git remote get-url hawkeye >/dev/null 2>&1; then
  git remote set-url hawkeye "$URL"
else
  git remote add hawkeye "$URL"
fi

BRANCH="$(git branch --show-current)"
echo "Pushing branch '$BRANCH' (and tagging as main on Hawkeye)…"
git push -u hawkeye "$BRANCH:main"
echo
echo "Done. Clone private Hawkeye with:"
echo "  git clone $URL"
echo "Public Autocode remains at origin (brandonbrown15/Autocode)."
