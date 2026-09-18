#!/usr/bin/env bash
# Install systemd units so Hawkeye starts automatically when the Jetson boots.
#
# Usage:
#   ./scripts/install_hawkeye_autostart.sh           # user units + linger (recommended)
#   ./scripts/install_hawkeye_autostart.sh system     # /etc/systemd/system (needs sudo)
#   ./scripts/install_hawkeye_autostart.sh --no-tunnel
#   ./scripts/install_hawkeye_autostart.sh --disable  # stop + disable units
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="user"
WITH_TUNNEL="${WITH_TUNNEL:-1}"
DISABLE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    user|system) MODE="$1"; shift ;;
    --no-tunnel) WITH_TUNNEL=0; shift ;;
    --with-tunnel) WITH_TUNNEL=1; shift ;;
    --disable) DISABLE=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

UNIT_DIR="$HOME/.config/systemd/user"
SYSCTL=(systemctl --user)
if [[ "$MODE" == "system" ]]; then
  UNIT_DIR="/etc/systemd/system"
  SYSCTL=(sudo systemctl)
fi

rewrite_unit() {
  local src="$1" dest="$2"
  ROOT="$ROOT" MODE="$MODE" UNIT_USER="$(id -un)" UNIT_GROUP="$(id -gn)" \
    SRC="$src" DEST="$dest" python3 - <<'PY'
import os
from pathlib import Path

src = Path(os.environ["SRC"])
dest = Path(os.environ["DEST"])
root = os.environ["ROOT"]
mode = os.environ["MODE"]
text = src.read_text().replace("/opt/autocode", root)
if mode == "system":
    text = text.replace("WantedBy=default.target", "WantedBy=multi-user.target")
    user = os.environ["UNIT_USER"]
    group = os.environ["UNIT_GROUP"]
    lines = text.splitlines()
    out = []
    for line in lines:
        out.append(line)
        if line.strip() == "[Service]":
            out.append(f"User={user}")
            out.append(f"Group={group}")
    text = "\n".join(out) + "\n"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(text)
print(f"  wrote {dest}")
PY
}

if [[ "$DISABLE" -eq 1 ]]; then
  "${SYSCTL[@]}" disable --now hawkeye-update.timer 2>/dev/null || true
  "${SYSCTL[@]}" disable --now hawkeye-tunnel.service 2>/dev/null || true
  "${SYSCTL[@]}" disable --now hawkeye-ui.service 2>/dev/null || true
  "${SYSCTL[@]}" disable --now autocode-ui.service 2>/dev/null || true
  echo "Hawkeye auto-start disabled ($MODE)."
  exit 0
fi

echo "Installing Hawkeye auto-start ($MODE) from $ROOT …"
mkdir -p "$UNIT_DIR"
rewrite_unit "$ROOT/cron/hawkeye-ui.service" "$UNIT_DIR/hawkeye-ui.service"
if [[ -f "$ROOT/cron/hawkeye-update.service" ]]; then
  rewrite_unit "$ROOT/cron/hawkeye-update.service" "$UNIT_DIR/hawkeye-update.service"
  cp "$ROOT/cron/hawkeye-update.timer" "$UNIT_DIR/hawkeye-update.timer"
fi

install_tunnel=0
if [[ "$WITH_TUNNEL" == "1" ]]; then
  if command -v cloudflared >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    [[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a || true
    if [[ -f "$HOME/.cloudflared/config.yml" ]] || [[ -n "${TUNNEL_TOKEN:-}" ]]; then
      rewrite_unit "$ROOT/cron/hawkeye-tunnel.service" "$UNIT_DIR/hawkeye-tunnel.service"
      install_tunnel=1
    else
      echo "NOTE: cloudflared present but no config/token — skipping tunnel unit."
      echo "      After tunnel setup, re-run: $0 ${MODE}"
    fi
  else
    echo "NOTE: cloudflared not installed — UI still auto-starts (localhost / Tailscale)."
  fi
fi

"${SYSCTL[@]}" daemon-reload

# User units only start at boot if lingering is enabled (no graphical login required).
if [[ "$MODE" == "user" ]]; then
  if command -v loginctl >/dev/null 2>&1; then
    if ! loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
      echo "Enabling systemd linger for $(id -un) (required for boot without login)…"
      sudo loginctl enable-linger "$(id -un)" || {
        echo "WARN: could not enable linger. Run: sudo loginctl enable-linger $(id -un)"
      }
    else
      echo "Linger already enabled for $(id -un)."
    fi
  fi
fi

# Keep Ollama up across reboots when the system unit exists.
if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
  sudo systemctl enable --now ollama 2>/dev/null || true
fi

"${SYSCTL[@]}" enable --now hawkeye-ui.service
if [[ -f "$UNIT_DIR/hawkeye-update.timer" ]]; then
  "${SYSCTL[@]}" enable --now hawkeye-update.timer
fi
if [[ "$install_tunnel" -eq 1 ]]; then
  "${SYSCTL[@]}" enable --now hawkeye-tunnel.service
fi

echo
echo "Hawkeye auto-start installed ($MODE)."
echo "  • hawkeye-ui.service       — dashboard + chat on boot"
[[ -f "$UNIT_DIR/hawkeye-update.timer" ]] && echo "  • hawkeye-update.timer     — pull GitHub every 5 min + refresh UI/LLM"
[[ "$install_tunnel" -eq 1 ]] && echo "  • hawkeye-tunnel.service   — Cloudflare → hawkeye.brownhawke.engineering"
echo
echo "Check:"
echo "  ${SYSCTL[*]} status hawkeye-ui.service"
[[ -f "$UNIT_DIR/hawkeye-update.timer" ]] && echo "  ${SYSCTL[*]} list-timers hawkeye-update.timer"
[[ -f "$ROOT/scripts/hawkeye_self_update.sh" ]] && echo "  ./scripts/hawkeye_self_update.sh --check"
echo
echo "Disable later:"
echo "  $0 ${MODE} --disable"
echo "  # or pause updates only:  HAWKEYE_UPDATE_ENABLED=0 in .env (or Account → Machine)"
