#!/usr/bin/env bash
# Echo OLLAMA_NUM_CTX, with a Jetson-safe cap when unset or dangerously high.
# Orin Nano shared memory cannot hold 7B + 64k KV cache reliably (HTTP 500).
set -euo pipefail

if [[ -n "${OLLAMA_NUM_CTX:-}" ]]; then
  CTX="$OLLAMA_NUM_CTX"
else
  if [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; then
    CTX=16384
  else
    CTX=65536
  fi
fi

# Cap unless explicitly overridden — prevents .env.example's old 65536 from OOMing Jetsons.
if [[ -z "${OLLAMA_ALLOW_HIGH_CTX:-}" ]] \
  && { [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; } \
  && [[ "$CTX" -gt 32768 ]]; then
  echo "16384" >&2
  echo "note: capped OLLAMA_NUM_CTX=$CTX → 16384 on Jetson (export OLLAMA_ALLOW_HIGH_CTX=1 to keep)" >&2
  CTX=16384
fi

echo "$CTX"
