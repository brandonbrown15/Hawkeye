#!/usr/bin/env bash
# Smoke: Hermes + Ollama can run a tool-ish coding turn (best-effort across Hermes CLIs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

export PATH="${HOME}/.local/bin:${HOME}/.hermes/bin:/usr/local/bin:${PATH}"

MODEL="${OLLAMA_MODEL:-coder-64k}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
SMOKE_DIR="$(mktemp -d /tmp/autocode-hermes-smoke.XXXXXX)"
MARKER="$SMOKE_DIR/SMOKE_OK.txt"

cleanup() { rm -rf "$SMOKE_DIR" 2>/dev/null || true; }
trap cleanup EXIT

echo "== Smoke Hermes tools =="
echo "workspace: $SMOKE_DIR"

if ! command -v hermes >/dev/null 2>&1; then
  echo "FAIL: hermes not on PATH (run ./hermes/install_hermes.sh)"
  exit 1
fi

if ! curl -fsS "http://${HOST}/api/tags" >/dev/null; then
  echo "FAIL: Ollama not reachable at http://${HOST}"
  exit 1
fi

if ! curl -fsS "http://${HOST}/api/tags" | grep -q "$MODEL"; then
  echo "WARN: model '$MODEL' not listed in ollama tags — continuing anyway"
fi

PROMPT="You are in directory ${SMOKE_DIR}. Create a file named SMOKE_OK.txt containing exactly the text OK. Use your file tools. Do not ask questions."

cd "$SMOKE_DIR"
set +e
# Try common Hermes invocation forms
hermes chat -q "$PROMPT" 2>"$SMOKE_DIR/hermes.err" | tee "$SMOKE_DIR/hermes.out"
rc=${PIPESTATUS[0]}
if [[ $rc -ne 0 ]]; then
  hermes -q "$PROMPT" 2>>"$SMOKE_DIR/hermes.err" | tee -a "$SMOKE_DIR/hermes.out"
  rc=${PIPESTATUS[0]}
fi
set -e

if [[ -f "$MARKER" ]] && grep -q "OK" "$MARKER"; then
  echo "PASS: Hermes created $MARKER"
  exit 0
fi

echo "FAIL: Hermes did not create SMOKE_OK.txt with OK"
echo "--- hermes stderr (tail) ---"
tail -n 40 "$SMOKE_DIR/hermes.err" 2>/dev/null || true
echo "--- hermes stdout (tail) ---"
tail -n 40 "$SMOKE_DIR/hermes.out" 2>/dev/null || true
echo
echo "Fix: ./hermes/configure_local_primary.sh && hermes doctor"
echo "If Hermes needs interactive model setup once: hermes setup (Custom endpoint ${HOST}/v1, model ${MODEL})"
exit 1
