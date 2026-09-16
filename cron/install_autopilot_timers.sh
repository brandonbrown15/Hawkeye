#!/usr/bin/env bash
# Install systemd timers: overnight (01:00) + continuous worker + optional UI service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-user}" # user | system
WITH_UI="${WITH_UI:-1}"

UNIT_DIR="$HOME/.config/systemd/user"
SYSCTL=(systemctl --user)
if [[ "$MODE" == "system" ]]; then
  UNIT_DIR="/etc/systemd/system"
  SYSCTL=(sudo systemctl)
fi

mkdir -p "$UNIT_DIR"

rewrite() {
  local src="$1" dest="$2"
  sed "s|/opt/autocode|${ROOT}|g" "$src" >"$dest"
}

rewrite "$ROOT/cron/autocode-overnight.service" "$UNIT_DIR/autocode-overnight.service"
cp "$ROOT/cron/autocode-overnight.timer" "$UNIT_DIR/autocode-overnight.timer"
rewrite "$ROOT/cron/autocode-worker.service" "$UNIT_DIR/autocode-worker.service"
cp "$ROOT/cron/autocode-worker.timer" "$UNIT_DIR/autocode-worker.timer"

if [[ "$WITH_UI" == "1" ]]; then
  rewrite "$ROOT/cron/autocode-ui.service" "$UNIT_DIR/autocode-ui.service"
fi

"${SYSCTL[@]}" daemon-reload
"${SYSCTL[@]}" enable --now autocode-overnight.timer
"${SYSCTL[@]}" enable --now autocode-worker.timer
if [[ "$WITH_UI" == "1" ]]; then
  "${SYSCTL[@]}" enable --now autocode-ui.service || true
fi

echo
echo "Installed Autocode timers ($MODE):"
echo "  • overnight  — daily 01:00 (batch)"
echo "  • worker     — every ~30 min when continuous is enabled"
[[ "$WITH_UI" == "1" ]] && echo "  • ui         — dashboard service (see scripts/ui.sh --remote)"
echo
echo "Live work requires in .env:"
echo "  AUTOCODE_AUTOPILOT_ENABLED=1"
echo "  AUTOCODE_CONTINUOUS_ENABLED=1   # for daytime / always-on coding"
echo
echo "Supervised once:  $ROOT/cron/overnight_run.sh --force"
echo "One work cycle:   $ROOT/cron/worker_run.sh --force"
echo "Dry-run:          $ROOT/cron/worker_run.sh --dry-run"
"${SYSCTL[@]}" list-timers 2>/dev/null | grep autocode || true
