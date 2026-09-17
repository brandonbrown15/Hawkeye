#!/usr/bin/env bash
# Non-interactive GitHub auth when GITHUB_TOKEN (or GH_TOKEN) is set.
# Falls back to clear PAT instructions (GitHub rejects account passwords).
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
if [[ -n "$TOKEN" ]]; then
  echo "$TOKEN" | gh auth login --with-token
  gh auth setup-git >/dev/null 2>&1 || true
  gh auth status
  echo "OK: gh authenticated via token"
  exit 0
fi

cat <<'EOF'
No GITHUB_TOKEN/GH_TOKEN in .env.

GitHub no longer accepts your account password for git/gh.
Use a Personal Access Token (PAT):

  1. https://github.com/settings/tokens
     Classic: repo scope  — or —  Fine-grained: Contents/Metadata read on brandonbrown15/Hawkeye
  2. On the Jetson, either:

       # A) put it in .env (recommended for this box)
       echo 'GITHUB_TOKEN=ghp_your_token_here' >> ~/Hawkeye/.env
       ./scripts/auth_github.sh

       # B) interactive browser/device flow
       gh auth login -h github.com -p https -w

       # C) paste PAT when git asks for Password
       git pull   # Username: brandonbrown15  Password: <PAT not your login password>

EOF
exit 1
