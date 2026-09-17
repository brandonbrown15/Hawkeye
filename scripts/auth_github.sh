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
# Trim BOM/CR/LF/spaces and accidental surrounding quotes from .env pastes
TOKEN="${TOKEN#"${TOKEN%%[![:space:]]*}"}"
TOKEN="${TOKEN%"${TOKEN##*[![:space:]]}"}"
TOKEN="${TOKEN//$'\r'/}"
if [[ "$TOKEN" == \"*\" && "$TOKEN" == *\" ]]; then TOKEN="${TOKEN:1:-1}"; fi
if [[ "$TOKEN" == \'*\' && "$TOKEN" == *\' ]]; then TOKEN="${TOKEN:1:-1}"; fi

if [[ -n "$TOKEN" ]]; then
  # Safe diagnostics (never print the secret)
  echo "Token loaded from env: length=${#TOKEN} prefix=${TOKEN:0:11}…"
  if [[ ! "$TOKEN" =~ ^(ghp_|github_pat_) ]]; then
    echo "WARN: token should start with ghp_ (classic) or github_pat_ (fine-grained)"
  fi
  if ! curl -fsS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      https://api.github.com/user | grep -q '^200$'; then
    code="$(curl -sS -o /tmp/gh-token-check.json -w "%{http_code}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      https://api.github.com/user || true)"
    echo "FAIL: GitHub API returned HTTP ${code} for this token (401 = bad/revoked/expired)."
    echo "  • Revoke old tokens that were pasted in chat"
    echo "  • Create a NEW fine-grained PAT with Contents+Metadata on repo Hawkeye"
    echo "  • Or use a classic PAT with 'repo' scope: https://github.com/settings/tokens"
    echo "  • Ensure .env has exactly: GITHUB_TOKEN=github_pat_...  (no quotes, no spaces)"
    echo "  • Or skip .env: gh auth login -h github.com -p https -w"
    head -c 200 /tmp/gh-token-check.json 2>/dev/null; echo
    exit 1
  fi
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
