#!/usr/bin/env bash
# Echo a Jetson-safe BASE_MODEL when unset.
# Orin Nano ~8GB: 3B Q4 @ 4k ctx is the proven default (1.5b was too weak;
# 7b often cudaMalloc-OOMs). Override anytime with BASE_MODEL=…
set -euo pipefail

if [[ -n "${BASE_MODEL:-}" ]]; then
  echo "$BASE_MODEL"
  exit 0
fi

model_name="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
if echo "$model_name" | grep -qi 'orin nano'; then
  # ~1.9GB Q4 — validated on Orin Nano Super with OLLAMA_NUM_CTX=4096
  echo "qwen2.5-coder:3b"
elif [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; then
  echo "qwen2.5-coder:3b"
else
  echo "qwen2.5-coder:7b"
fi
