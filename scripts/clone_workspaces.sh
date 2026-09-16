#!/usr/bin/env bash
# Print how to clone workspace repos from WORKSPACE_REPOS in .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

WS="${WORKSPACE_ROOT:-$HOME/workspaces}"
mkdir -p "$WS"

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
