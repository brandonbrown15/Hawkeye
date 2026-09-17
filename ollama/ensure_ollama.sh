#!/usr/bin/env bash
# Ensure Ollama is listening on OLLAMA_HOST before smoke / model create.
# Safe to re-run. Prefer systemd when available; otherwise start a user serve.
#
# Usage:
#   ./ollama/ensure_ollama.sh           # start if down
#   ./ollama/ensure_ollama.sh --restart  # stop + start with current OLLAMA_MODELS
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-24h}"
WAIT_SEC="${OLLAMA_READY_WAIT_SEC:-90}"
URL="http://${HOST}/api/tags"
RESTART=0
[[ "${1:-}" == "--restart" || "${1:-}" == "-r" ]] && RESTART=1

reachable() {
  curl -fsS --max-time 2 "$URL" >/dev/null 2>&1
}

stop_ollama() {
  echo "Stopping Ollama so it can reload OLLAMA_MODELS=${OLLAMA_MODELS:-"(default)"}…"
  if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
    sudo systemctl stop ollama 2>/dev/null || true
  fi
  # Background serve from a prior ensure_ollama run
  if [[ -f "$ROOT/state/ollama-serve.pid" ]]; then
    kill "$(cat "$ROOT/state/ollama-serve.pid")" 2>/dev/null || true
    rm -f "$ROOT/state/ollama-serve.pid"
  fi
  pkill -f '[o]llama serve' 2>/dev/null || true
  # Give the port a moment to free
  sleep 1
}

start_via_systemd() {
  if ! systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
    return 1
  fi
  if [[ -n "${OLLAMA_MODELS:-}" ]] && command -v sudo >/dev/null 2>&1; then
    sudo mkdir -p /etc/systemd/system/ollama.service.d
    sudo tee /etc/systemd/system/ollama.service.d/autocode-models.conf >/dev/null <<EOF
[Service]
Environment="OLLAMA_MODELS=${OLLAMA_MODELS}"
Environment="OLLAMA_KEEP_ALIVE=${KEEP_ALIVE}"
Environment="OLLAMA_HOST=${HOST}"
EOF
    sudo systemctl daemon-reload
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo systemctl enable --now ollama 2>/dev/null || sudo systemctl start ollama 2>/dev/null || return 1
  else
    systemctl --user start ollama 2>/dev/null || return 1
  fi
  return 0
}

start_background() {
  mkdir -p "$HOME/.local/share/ollama" "$ROOT/logs" "$ROOT/state" 2>/dev/null || true
  [[ -n "${OLLAMA_MODELS:-}" ]] && mkdir -p "$OLLAMA_MODELS"
  export OLLAMA_HOST="$HOST" OLLAMA_KEEP_ALIVE="$KEEP_ALIVE"
  [[ -n "${OLLAMA_MODELS:-}" ]] && export OLLAMA_MODELS
  # Prefer the system binary that sits next to lib/ollama/llama-server
  local bin="ollama"
  [[ -x /usr/local/bin/ollama ]] && bin=/usr/local/bin/ollama
  [[ -x /usr/bin/ollama ]] && [[ ! -x /usr/local/bin/ollama ]] && bin=/usr/bin/ollama
  local runner=""
  runner="$(find /usr/local/lib/ollama /usr/lib/ollama -name llama-server -type f 2>/dev/null | head -1 || true)"
  if [[ -z "$runner" ]]; then
    echo "FAIL: llama-server runner missing — run: ./ollama/install_ollama_jetson.sh"
    echo "      (CLI-only installs list models but every chat returns HTTP 500)"
    exit 1
  fi
  nohup "$bin" serve >>"$ROOT/logs/ollama-serve.log" 2>&1 &
  echo $! >"$ROOT/state/ollama-serve.pid" 2>/dev/null || true
  echo "Started background: $bin serve (log: logs/ollama-serve.log)"
  echo "  runner: $runner"
  [[ -n "${OLLAMA_MODELS:-}" ]] && echo "  OLLAMA_MODELS=$OLLAMA_MODELS"
}

if ! command -v ollama >/dev/null 2>&1; then
  echo "FAIL: ollama not on PATH — run ./ollama/install_ollama_jetson.sh"
  exit 1
fi

if [[ "$RESTART" -eq 1 ]]; then
  stop_ollama
elif reachable; then
  echo "Ollama already up at http://${HOST}"
  if [[ -n "${OLLAMA_MODELS:-}" ]]; then
    echo "Note: if you just changed OLLAMA_MODELS, re-run: ./ollama/ensure_ollama.sh --restart"
  fi
  exit 0
fi

echo "Ollama not reachable at http://${HOST} — starting…"
[[ -n "${OLLAMA_MODELS:-}" ]] && echo "  OLLAMA_MODELS=$OLLAMA_MODELS"

start_via_systemd || true
if ! reachable; then
  start_background
fi

deadline=$((SECONDS + WAIT_SEC))
while (( SECONDS < deadline )); do
  if reachable; then
    echo "Ollama ready at http://${HOST}"
    exit 0
  fi
  sleep 1
done

echo "FAIL: Ollama still not reachable after ${WAIT_SEC}s at http://${HOST}"
echo "  Check: systemctl status ollama"
echo "  Or:    OLLAMA_HOST=$HOST ollama serve"
echo "  Log:   $ROOT/logs/ollama-serve.log"
exit 1
