#!/usr/bin/env bash
# Ensure Ollama is listening on OLLAMA_HOST before smoke / model create.
# Safe to re-run. Prefer systemd when available; otherwise start a user serve.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-24h}"
WAIT_SEC="${OLLAMA_READY_WAIT_SEC:-60}"
URL="http://${HOST}/api/tags"

reachable() {
  curl -fsS --max-time 2 "$URL" >/dev/null 2>&1
}

if ! command -v ollama >/dev/null 2>&1; then
  echo "FAIL: ollama not on PATH — run ./ollama/install_ollama_jetson.sh"
  exit 1
fi

if reachable; then
  echo "Ollama already up at http://${HOST}"
  exit 0
fi

echo "Ollama not reachable at http://${HOST} — starting…"

if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
  if command -v sudo >/dev/null 2>&1; then
    sudo systemctl enable --now ollama 2>/dev/null || sudo systemctl start ollama 2>/dev/null || true
  else
    systemctl --user start ollama 2>/dev/null || true
  fi
fi

if ! reachable; then
  mkdir -p "$HOME/.local/share/ollama" "$ROOT/logs" "$ROOT/state" 2>/dev/null || true
  export OLLAMA_HOST="$HOST" OLLAMA_KEEP_ALIVE="$KEEP_ALIVE"
  [[ -n "${OLLAMA_MODELS:-}" ]] && export OLLAMA_MODELS
  nohup ollama serve >>"$ROOT/logs/ollama-serve.log" 2>&1 &
  echo $! >"$ROOT/state/ollama-serve.pid" 2>/dev/null || true
  echo "Started background: ollama serve (log: logs/ollama-serve.log)"
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
