#!/usr/bin/env bash
# Clone workspace repos from WORKSPACE_REPOS in .env into a writable WORKSPACE_ROOT.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

WS="$(bash "$ROOT/scripts/resolve_workspace_root.sh")"
mkdir -p "$WS"

# Persist the resolved path when .env still points at an unwritable /opt default.
ENV_FILE="$ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  cur="$(grep -E '^WORKSPACE_ROOT=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  cur="${cur/#\~/$HOME}"
  if [[ -z "$cur" || "$cur" != "$WS" ]]; then
    if grep -q '^WORKSPACE_ROOT=' "$ENV_FILE" 2>/dev/null; then
      grep -v '^WORKSPACE_ROOT=' "$ENV_FILE" >"${ENV_FILE}.tmp" || true
      mv "${ENV_FILE}.tmp" "$ENV_FILE"
    fi
    echo "WORKSPACE_ROOT=$WS" >>"$ENV_FILE"
    echo "Updated .env WORKSPACE_ROOT=$WS"
  fi
fi

echo "Workspace root: $WS"
if [[ -z "${WORKSPACE_REPOS:-}" ]]; then
  echo "Set WORKSPACE_REPOS in .env to space-separated git clone URLs, e.g.:"
  echo "  WORKSPACE_REPOS=\"git@github.com:you/app.git https://github.com/you/other.git\""
  exit 0
fi

for url in $WORKSPACE_REPOS; do
  name="$(basename "$url" .git)"
  dest="$WS/$name"
  if [[ -d "$dest/.git" ]]; then
    echo "Exists: $dest"
  else
    echo "Clone: git clone $url $dest"
    git clone "$url" "$dest"
  fi
done
