#!/usr/bin/env bash
# Non-interactive GitHub auth when GITHUB_TOKEN (or GH_TOKEN) is set.
# Falls back to reporting interactive gh auth login if no token.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh missing — run ./bootstrap/03_install_gh.sh first"
  exit 1
fi

if gh auth status >/dev/null 2>&1; then
  echo "gh already authenticated"
  gh auth status 2>&1 | head -5 || true
  exit 0
fi

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "$TOKEN" ]]; then
  echo "No GITHUB_TOKEN/GH_TOKEN in env."
  echo "Either export a fine-scoped PAT, or run interactively: gh auth login"
  exit 1
fi

echo "$TOKEN" | gh auth login --with-token
gh auth setup-git >/dev/null 2>&1 || true
gh auth status
echo "OK: gh authenticated via token"
