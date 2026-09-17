#!/usr/bin/env bash
# Pull base model + create coder-64k from Modelfile, then smoke chat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

BASE_MODEL="${BASE_MODEL:-qwen2.5-coder:7b}"
TARGET_MODEL="${OLLAMA_MODEL:-coder-64k}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
NUM_CTX="$(bash "$ROOT/ollama/default_num_ctx.sh")"
export OLLAMA_NUM_CTX="$NUM_CTX"

# Persist Jetson-safe ctx into .env when missing / still at an unsafe 65536 on tegra.
ENV_FILE="$ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  if ! grep -q '^OLLAMA_NUM_CTX=' "$ENV_FILE" 2>/dev/null \
    || { [[ -f /etc/nv_tegra_release ]] && grep -q '^OLLAMA_NUM_CTX=65536$' "$ENV_FILE" 2>/dev/null; }; then
    grep -v '^OLLAMA_NUM_CTX=' "$ENV_FILE" >"${ENV_FILE}.tmp" 2>/dev/null || true
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
    echo "OLLAMA_NUM_CTX=${NUM_CTX}" >>"$ENV_FILE"
    echo "Updated .env OLLAMA_NUM_CTX=${NUM_CTX}"
  fi
fi

# Make sure daemon is up *with* current OLLAMA_MODELS (SSD path).
bash "$ROOT/ollama/ensure_ollama.sh"

echo "== Pull base model: $BASE_MODEL =="
ollama pull "$BASE_MODEL"

# Rewrite FROM + num_ctx for this host
tmp="$(mktemp)"
sed \
  -e "s/^FROM .*/FROM ${BASE_MODEL}/" \
  -e "s/^PARAMETER num_ctx .*/PARAMETER num_ctx ${NUM_CTX}/" \
  "$ROOT/ollama/Modelfile.coder-64k" >"$tmp"
echo "Using PARAMETER num_ctx ${NUM_CTX} (override with OLLAMA_NUM_CTX=...)"

echo "== Create $TARGET_MODEL =="
ollama create "$TARGET_MODEL" -f "$tmp"
rm -f "$tmp"

echo "== List models =="
ollama list || true
curl -fsS "http://${HOST}/api/tags" | head -c 800 || true
echo

smoke_chat() {
  local label="$1" path="$2" body="$3" out="$4"
  echo "== Smoke ${label} =="
  local code
  set +e
  code="$(curl -sS -o "$out" -w '%{http_code}' "http://${HOST}${path}" \
    -H 'Content-Type: application/json' \
    -d "$body")"
  set -e
  echo "HTTP $code"
  head -c 1200 "$out" 2>/dev/null || true
  echo
  [[ "$code" == "200" ]]
}

# Tiny completion first — proves weights load without allocating full KV cache.
TINY_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false,\"options\":{\"num_ctx\":2048,\"num_predict\":16}}"
FULL_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false,\"options\":{\"num_ctx\":${NUM_CTX},\"num_predict\":16}}"
V1_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":16}"

if smoke_chat "/api/chat (num_ctx=2048)" "/api/chat" "$TINY_BODY" /tmp/coder-64k-smoke-tiny.json; then
  echo "PASS: model loads and answers"
else
  echo "FAIL: model listed but inference 500 — check logs/ollama-serve.log (often VRAM / GPU)"
  echo "  Try: ollama run ${TARGET_MODEL} OK"
  echo "  Or smaller base: BASE_MODEL=qwen2.5-coder:3b ./ollama/create_coder_64k.sh"
  exit 1
fi

if smoke_chat "/api/chat (num_ctx=${NUM_CTX})" "/api/chat" "$FULL_BODY" /tmp/coder-64k-smoke.json; then
  echo "PASS: full num_ctx=${NUM_CTX} works"
else
  echo "WARN: full num_ctx=${NUM_CTX} failed — lower OLLAMA_NUM_CTX (e.g. 8192) and recreate"
fi

if smoke_chat "/v1/chat/completions" "/v1/chat/completions" "$V1_BODY" /tmp/coder-64k-smoke-v1.json; then
  echo "PASS: /v1/chat/completions responded"
else
  echo "WARN: /v1 error — Hermes/UI can still use native /api/chat"
fi

echo
echo "Verify with: ollama ps"
echo "Done. Next: ./hermes/configure_local_primary.sh"
