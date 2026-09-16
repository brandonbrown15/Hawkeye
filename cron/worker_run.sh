#!/usr/bin/env bash
# Always-on project autopilot — drains Ready Notion tasks until the project is finished.
# Uses the same orchestrator as overnight_run.sh, with a flock so runs never overlap.
#
# Live timer runs need:
#   AUTOCODE_AUTOPILOT_ENABLED=1
#   AUTOCODE_CONTINUOUS_ENABLED=1
# Or pass --force for a supervised cycle.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

STATE_DIR="${ROOT}/state"
LOG_DIR="${ROOT}/logs"
mkdir -p "$STATE_DIR" "$LOG_DIR"

STAMP="$(date -Iseconds | tr ':' '-')"
LOG="$LOG_DIR/worker-${STAMP}.log"
LOCK="$STATE_DIR/run.lock"

exec > >(tee -a "$LOG") 2>&1

echo "== Autocode work cycle @ $STAMP =="

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

# Continuous mode gate (timer): need both autopilot + continuous flags.
if [[ "$FORCE" -eq 0 \
  && " $JOINED " != *" --mock "* \
  && " $JOINED " != *" --dry-run "* ]]; then
  if [[ "${AUTOCODE_AUTOPILOT_ENABLED:-0}" != "1" ]]; then
    echo "AUTOCODE_AUTOPILOT_ENABLED!=1 — refusing live work cycle."
    echo "Enable after a supervised run, or: $0 --force"
    exit 0
  fi
  if [[ "${AUTOCODE_CONTINUOUS_ENABLED:-0}" != "1" ]]; then
    echo "AUTOCODE_CONTINUOUS_ENABLED!=1 — continuous worker idle (overnight timer still OK)."
    exit 0
  fi
fi

if [[ " ${PASS_ARGS[*]} " != *" --mock "* \
  && " ${PASS_ARGS[*]} " != *" --dry-run "* \
  && -z "${NOTION_TOKEN:-}" ]]; then
  echo "NOTION_TOKEN unset — aborting or pass --mock / --dry-run"
  exit 1
fi

# Default continuous batch is small (1 task) so daytime work stays snappy.
LIMIT="${AUTOCODE_MAX_TASKS_PER_CYCLE:-1}"
HAS_LIMIT=0
for arg in "${PASS_ARGS[@]}"; do
  if [[ "$arg" == "--limit" ]]; then HAS_LIMIT=1; break; fi
done
if [[ "$HAS_LIMIT" -eq 0 ]]; then
  PASS_ARGS+=(--limit "$LIMIT")
fi

# Drain Ready queue each tick (project autopilot until finished).
DRAIN="${AUTOCODE_DRAIN_UNTIL_EMPTY:-1}"
HAS_DRAIN=0
for arg in "${PASS_ARGS[@]}"; do
  if [[ "$arg" == "--drain" || "$arg" == "--no-drain" ]]; then HAS_DRAIN=1; break; fi
done
if [[ "$HAS_DRAIN" -eq 0 && "$DRAIN" == "1" ]]; then
  PASS_ARGS+=(--drain)
fi

# Routine health / bug checklist seed before coding.
if [[ " ${PASS_ARGS[*]} " != *" --mock "* && "${AUTOCODE_HEALTH_FEED_ENABLED:-1}" == "1" ]]; then
  python3 -m orchestrator.self_feed --health || true
fi

echo "limit=${LIMIT} wall=${AUTOCODE_MAX_WALL_MINUTES:-90}m continuous=${AUTOCODE_CONTINUOUS_ENABLED:-0}"

# Non-blocking lock: if overnight or another cycle is running, skip this tick.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "Another Autocode run holds $LOCK — skipping this cycle."
  exit 0
fi

python3 "$ROOT/orchestrator/run_night.py" "${PASS_ARGS[@]}"
echo "Done. Log: $LOG"
