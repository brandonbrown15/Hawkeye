#!/usr/bin/env bash
# Remote intervene controls: pause | resume | abort | skip <id> | clear | ping
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
cd "$ROOT"
if [[ $# -lt 1 ]]; then
  echo "usage: $0 pause|resume|abort|skip <task_id>|clear|ping|status"
  exit 1
fi
cmd="$1"
shift
exec python3 -m orchestrator.ops "$cmd" "$@"
