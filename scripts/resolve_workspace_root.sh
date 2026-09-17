#!/usr/bin/env bash
# Print a writable WORKSPACE_ROOT. Prefer env / data SSD / home — never force /opt.
# Usage: source this, or: WS="$(./scripts/resolve_workspace_root.sh)"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Preserve explicit overrides (caller / CI) over .env defaults.
_pre_ws="${WORKSPACE_ROOT-}"
_pre_data="${AUTOCODE_DATA_ROOT-}"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
[[ -n "${_pre_ws}" ]] && WORKSPACE_ROOT="$_pre_ws"
[[ -n "${_pre_data}" ]] && AUTOCODE_DATA_ROOT="$_pre_data"

_writable_dir() {
  local d="$1"
  [[ -z "$d" ]] && return 1
  # Expand leading ~
  [[ "$d" == ~* ]] && d="${d/#\~/$HOME}"
  if [[ -d "$d" ]]; then
    [[ -w "$d" ]] && { echo "$d"; return 0; }
    return 1
  fi
  if mkdir -p "$d" 2>/dev/null && [[ -w "$d" ]]; then
    echo "$d"
    return 0
  fi
  return 1
}

pick() {
  local cand
  for cand in \
    "${WORKSPACE_ROOT:-}" \
    "${AUTOCODE_DATA_ROOT:+$AUTOCODE_DATA_ROOT/workspaces}" \
    "$HOME/workspaces" \
    "$HOME/autocode-data/workspaces"
  do
    [[ -z "$cand" ]] && continue
    if _writable_dir "$cand"; then
      return 0
    fi
  done
  # Last resort: under the repo (always writable for the clone owner)
  _writable_dir "$ROOT/workspaces"
}

WS="$(pick)"
echo "$WS"
