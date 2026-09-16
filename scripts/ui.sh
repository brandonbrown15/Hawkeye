#!/usr/bin/env bash
# Launch the Autocode dashboard.
# Usage:
#   ./scripts/ui.sh                  # localhost only (default)
#   ./scripts/ui.sh --remote         # bind Tailscale IP (or 0.0.0.0 fallback)
#   ./scripts/ui.sh --host 0.0.0.0   # explicit bind
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

HOST="${AUTOCODE_UI_HOST:-127.0.0.1}"
PORT="${AUTOCODE_UI_PORT:-8787}"
REMOTE=0

tailscale_ip() {
  if command -v tailscale >/dev/null 2>&1; then
    tailscale ip -4 2>/dev/null | head -n1 || true
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --remote|--tailscale)
      REMOTE=1
      shift
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--remote] [--host ADDR] [--port PORT]

  (default)   Bind 127.0.0.1 — open on this machine, or SSH tunnel:
                ssh -L ${PORT}:127.0.0.1:${PORT} jetson

  --remote    Bind Tailscale IP when available (else 0.0.0.0).
              Then open http://<tailscale-ip>:${PORT}/ from your phone/laptop
              on the same Tailscale network.

Env: AUTOCODE_UI_HOST, AUTOCODE_UI_PORT, AUTOCODE_UI_REMOTE=1
EOF
      exit 0
      ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ "$REMOTE" -eq 1 || "${AUTOCODE_UI_REMOTE:-0}" == "1" ]]; then
  TS_IP="$(tailscale_ip)"
  if [[ -n "$TS_IP" ]]; then
    HOST="$TS_IP"
    echo "Remote UI via Tailscale → http://${HOST}:${PORT}/"
  else
    HOST="0.0.0.0"
    echo "Remote UI bind 0.0.0.0:${PORT} (no Tailscale IP found)."
    echo "Prefer Tailscale: ./bootstrap/04_install_tailscale.sh && sudo tailscale up"
  fi
fi

export AUTOCODE_UI_HOST="$HOST"
export AUTOCODE_UI_PORT="$PORT"

echo "Starting Autocode UI on http://${HOST}:${PORT}/"
if [[ "$HOST" == "127.0.0.1" || "$HOST" == "localhost" ]]; then
  echo "Tip (remote): ./scripts/ui.sh --remote   OR   ssh -L ${PORT}:127.0.0.1:${PORT} jetson"
fi
exec python3 -m ui.server
