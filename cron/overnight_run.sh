#!/usr/bin/env bash
# Overnight autopilot entrypoint → orchestrator (local-first + cloud escalate).
# Timer runs require AUTOCODE_AUTOPILOT_ENABLED=1 unless --force / --mock / --dry-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

STATE_DIR="${ROOT}/state"
LOG_DIR="${ROOT}/logs"
mkdir -p "$STATE_DIR" "$LOG_DIR"

STAMP="$(date -Iseconds | tr ':' '-')"
LOG="$LOG_DIR/nightly-${STAMP}.log"

exec > >(tee -a "$LOG") 2>&1

echo "== Autocode overnight run @ $STAMP =="
echo "max_tasks=${AUTOCODE_MAX_TASKS_PER_NIGHT:-2} wall=${AUTOCODE_MAX_WALL_MINUTES:-90}m attempts=${AUTOCODE_MAX_LOCAL_ATTEMPTS:-2}"

EXTRA=("$@")
JOINED=" ${EXTRA[*]} "

FORCE=0
PASS_ARGS=()
for arg in "${EXTRA[@]}"; do
  if [[ "$arg" == "--force" ]]; then
    FORCE=1
  else
    PASS_ARGS+=("$arg")
  fi
done

# Safety: systemd timer must not run unattended until operator flips the flag.
if [[ "$FORCE" -eq 0 \
  && " $JOINED " != *" --mock "* \
  && " $JOINED " != *" --dry-run "* \
  && "${AUTOCODE_AUTOPILOT_ENABLED:-0}" != "1" ]]; then
  echo "AUTOCODE_AUTOPILOT_ENABLED!=1 — refusing live overnight run."
  echo "After a supervised night, set AUTOCODE_AUTOPILOT_ENABLED=1 in .env"
  echo "Or run once with: $0 --force ${PASS_ARGS[*]}"
  exit 0
fi

# Live mode needs Notion; mock/demo does not.
if [[ " ${PASS_ARGS[*]} " != *" --mock "* && -z "${NOTION_TOKEN:-}" ]]; then
  echo "NOTION_TOKEN unset — aborting (configure local .env) or pass --mock"
  exit 1
fi

# Share a lock with the continuous worker so cycles never overlap.
LOCK="$STATE_DIR/run.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Another Autocode run holds $LOCK — overnight skipped this tick."
  exit 0
fi

python3 "$ROOT/orchestrator/run_night.py" "${PASS_ARGS[@]}"
echo "Done. Log: $LOG"
