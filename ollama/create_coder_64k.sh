#!/usr/bin/env bash
# Pull base model + create coder-64k from Modelfile, then smoke chat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

BASE_MODEL="$(bash "$ROOT/ollama/default_base_model.sh")"
TARGET_MODEL="${OLLAMA_MODEL:-coder-64k}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
NUM_CTX="$(bash "$ROOT/ollama/default_num_ctx.sh")"
# 0 = CPU-only (slow, but works when CUDA unified memory is exhausted)
NUM_GPU="${OLLAMA_NUM_GPU:-}"
export OLLAMA_NUM_CTX="$NUM_CTX"
export BASE_MODEL

ENV_FILE="$ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  if ! grep -q '^OLLAMA_NUM_CTX=' "$ENV_FILE" 2>/dev/null \
    || { [[ -f /etc/nv_tegra_release ]] && grep -Eq '^OLLAMA_NUM_CTX=(65536|16384)$' "$ENV_FILE" 2>/dev/null; }; then
    grep -v '^OLLAMA_NUM_CTX=' "$ENV_FILE" >"${ENV_FILE}.tmp" 2>/dev/null || true
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
    echo "OLLAMA_NUM_CTX=${NUM_CTX}" >>"$ENV_FILE"
    echo "Updated .env OLLAMA_NUM_CTX=${NUM_CTX}"
  fi
  if [[ -f /etc/nv_tegra_release ]]; then
    if ! grep -q '^BASE_MODEL=' "$ENV_FILE" 2>/dev/null; then
      echo "BASE_MODEL=${BASE_MODEL}" >>"$ENV_FILE"
      echo "Updated .env BASE_MODEL=${BASE_MODEL}"
    elif tr -d '\0' </proc/device-tree/model 2>/dev/null | grep -qi 'orin nano'; then
      # Orin Nano: keep 3b as the supported default.
      # - Upgrade legacy 1.5b pins to 3b (unless BASE_MODEL_FORCE keeps current)
      # - Downgrade 7b → 3b (7b usually CUDA-OOMs on 8GB)
      # Never silently replace an explicit 3b (or BASE_MODEL_FORCE) pin.
      if [[ -z "${BASE_MODEL_FORCE:-}" ]] \
        && grep -Eq '^BASE_MODEL=qwen2.5-coder:(1\.5b|7b)$' "$ENV_FILE" 2>/dev/null; then
        grep -v '^BASE_MODEL=' "$ENV_FILE" >"${ENV_FILE}.tmp" || true
        mv "${ENV_FILE}.tmp" "$ENV_FILE"
        BASE_MODEL="qwen2.5-coder:3b"
        echo "BASE_MODEL=${BASE_MODEL}" >>"$ENV_FILE"
        echo "Updated .env BASE_MODEL=${BASE_MODEL} (Orin Nano default)"
      fi
    fi
  fi
fi

echo "Base model: $BASE_MODEL"
[[ -n "$NUM_GPU" ]] && echo "OLLAMA_NUM_GPU=$NUM_GPU"

bash "$ROOT/ollama/ensure_ollama.sh"

echo "== Pull base model: $BASE_MODEL =="
ollama pull "$BASE_MODEL"

tmp="$(mktemp)"
{
  sed \
    -e "s/^FROM .*/FROM ${BASE_MODEL}/" \
    -e "s/^PARAMETER num_ctx .*/PARAMETER num_ctx ${NUM_CTX}/" \
    "$ROOT/ollama/Modelfile.coder-64k"
  if [[ -n "$NUM_GPU" ]]; then
    echo "PARAMETER num_gpu ${NUM_GPU}"
  fi
} >"$tmp"
echo "Using PARAMETER num_ctx ${NUM_CTX}"
[[ -n "$NUM_GPU" ]] && echo "Using PARAMETER num_gpu ${NUM_GPU}"

echo "== Create $TARGET_MODEL =="
ollama create "$TARGET_MODEL" -f "$tmp"
rm -f "$tmp"

echo "== List models =="
ollama list || true
curl -fsS "http://${HOST}/api/tags" | head -c 800 || true
echo

# Free unified memory before first load (critical on Orin Nano).
if [[ -f /etc/nv_tegra_release ]]; then
  bash "$ROOT/ollama/prepare_jetson_memory.sh" || true
fi

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

TINY_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false,\"options\":{\"num_ctx\":2048,\"num_predict\":16}}"
FULL_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false,\"options\":{\"num_ctx\":${NUM_CTX},\"num_predict\":16}}"
V1_BODY="{\"model\":\"${TARGET_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":16}"

if smoke_chat "/api/chat (num_ctx=2048)" "/api/chat" "$TINY_BODY" /tmp/coder-64k-smoke-tiny.json; then
  echo "PASS: model loads and answers"
else
  echo "FAIL: model listed but inference failed — see body above"
  if grep -qi 'llama-server binary not found' /tmp/coder-64k-smoke-tiny.json 2>/dev/null; then
    echo
    echo "Root cause: Ollama runner missing (llama-server)."
    echo "  Fix:  ./ollama/install_ollama_jetson.sh"
  elif grep -qi 'out of memory\|cudaMalloc\|unable to allocate CUDA' /tmp/coder-64k-smoke-tiny.json 2>/dev/null; then
    echo
    echo "Root cause: unified-memory CUDA OOM on this Jetson."
    echo "  1) Free mem:  ./ollama/prepare_jetson_memory.sh"
    echo "     systemctl --user stop hawkeye-ui.service 2>/dev/null || true"
    echo "  2) Smaller:   BASE_MODEL=qwen2.5-coder:1.5b OLLAMA_NUM_CTX=4096 ./ollama/create_coder_64k.sh"
    echo "  3) CPU-only:  OLLAMA_NUM_GPU=0 BASE_MODEL=qwen2.5-coder:3b OLLAMA_NUM_CTX=4096 ./ollama/create_coder_64k.sh"
    echo "     (slow, but reliable when GPU memory is exhausted)"
  else
    echo "  Check: logs/ollama-serve.log"
    echo "  Try:   ollama run ${TARGET_MODEL} OK"
  fi
  exit 1
fi

if smoke_chat "/api/chat (num_ctx=${NUM_CTX})" "/api/chat" "$FULL_BODY" /tmp/coder-64k-smoke.json; then
  echo "PASS: full num_ctx=${NUM_CTX} works"
else
  echo "WARN: full num_ctx=${NUM_CTX} failed — lower OLLAMA_NUM_CTX and recreate"
fi

if smoke_chat "/v1/chat/completions" "/v1/chat/completions" "$V1_BODY" /tmp/coder-64k-smoke-v1.json; then
  echo "PASS: /v1/chat/completions responded"
else
  echo "WARN: /v1 error — Hermes/UI can still use native /api/chat"
fi

echo
echo "Verify with: ollama ps"
echo "Done. Next: ./hermes/configure_local_primary.sh"
