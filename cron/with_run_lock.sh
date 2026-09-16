#!/usr/bin/env bash
# Shared flock so overnight + continuous cycles never overlap.
# Sourced or used via: flock path -c '...'
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="${ROOT}/state/run.lock"
mkdir -p "${ROOT}/state"
exec 9>"$LOCK"
flock -n 9 || {
  echo "Autocode run already in progress ($LOCK)"
  exit 0
}
exec "$@"
