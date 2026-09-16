#!/usr/bin/env bash
# Pull base model + create coder-64k from Modelfile, then smoke OpenAI-compatible chat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

BASE_MODEL="${BASE_MODEL:-qwen2.5-coder:7b}"
TARGET_MODEL="${OLLAMA_MODEL:-coder-64k}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

echo "== Pull base model: $BASE_MODEL =="
ollama pull "$BASE_MODEL"

# Rewrite FROM line if BASE_MODEL differs from Modelfile default
tmp="$(mktemp)"
sed "s/^FROM .*/FROM ${BASE_MODEL}/" "$ROOT/ollama/Modelfile.coder-64k" >"$tmp"

echo "== Create $TARGET_MODEL =="
ollama create "$TARGET_MODEL" -f "$tmp"
rm -f "$tmp"

echo "== Smoke /v1/chat/completions =="
curl -fsS "http://${HOST}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":16}" \
  | tee /tmp/coder-64k-smoke.json

echo
echo "Verify context with: ollama ps"
echo "Done. Next: ./hermes/install_hermes.sh"
