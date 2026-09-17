#!/usr/bin/env bash
# Echo OLLAMA_NUM_CTX, with a Jetson-safe cap when unset or dangerously high.
set -euo pipefail

if [[ -n "${OLLAMA_NUM_CTX:-}" ]]; then
  CTX="$OLLAMA_NUM_CTX"
else
  model_name="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
  if echo "$model_name" | grep -qi 'orin nano'; then
    CTX=4096
  elif [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; then
    CTX=8192
  else
    CTX=65536
  fi
fi

# Cap unless explicitly overridden
if [[ -z "${OLLAMA_ALLOW_HIGH_CTX:-}" ]] \
  && { [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; } \
  && [[ "$CTX" -gt 8192 ]]; then
  model_name="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
  if echo "$model_name" | grep -qi 'orin nano'; then
    echo "note: capped OLLAMA_NUM_CTX=$CTX → 4096 on Orin Nano" >&2
    CTX=4096
  else
    echo "note: capped OLLAMA_NUM_CTX=$CTX → 8192 on Jetson" >&2
    CTX=8192
  fi
fi

echo "$CTX"
