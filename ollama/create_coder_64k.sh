#!/usr/bin/env bash
# Pull base model + create coder-64k from Modelfile, then smoke chat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

BASE_MODEL="${BASE_MODEL:-qwen2.5-coder:7b}"
TARGET_MODEL="${OLLAMA_MODEL:-coder-64k}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

# Make sure daemon is up *with* current OLLAMA_MODELS (SSD path).
bash "$ROOT/ollama/ensure_ollama.sh"

echo "== Pull base model: $BASE_MODEL =="
ollama pull "$BASE_MODEL"

# Rewrite FROM line if BASE_MODEL differs from Modelfile default
tmp="$(mktemp)"
sed "s/^FROM .*/FROM ${BASE_MODEL}/" "$ROOT/ollama/Modelfile.coder-64k" >"$tmp"

echo "== Create $TARGET_MODEL =="
ollama create "$TARGET_MODEL" -f "$tmp"
rm -f "$tmp"

echo "== List models =="
ollama list || true
curl -fsS "http://${HOST}/api/tags" | head -c 800 || true
echo

echo "== Smoke /api/chat =="
# Native API is more reliable on Jetson than OpenAI /v1 (which can 500 under high num_ctx).
if curl -fsS "http://${HOST}/api/chat" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false,\"options\":{\"num_predict\":16}}" \
  | tee /tmp/coder-64k-smoke.json
then
  echo
  echo "PASS: /api/chat responded"
else
  echo
  echo "WARN: /api/chat smoke failed — model may still be listed; try: ollama run ${TARGET_MODEL} OK"
fi

echo "== Smoke /v1/chat/completions (optional) =="
if curl -fsS "http://${HOST}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":16}" \
  | tee /tmp/coder-64k-smoke-v1.json
then
  echo
  echo "PASS: /v1/chat/completions responded"
else
  echo
  echo "WARN: /v1 returned an error (common on Jetson with large num_ctx). Hermes/UI can use /api/chat."
fi

echo
echo "Verify context with: ollama ps"
echo "Done. Next: ./hermes/configure_local_primary.sh"
