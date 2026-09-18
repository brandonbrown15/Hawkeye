#!/usr/bin/env bash
# Echo a Jetson-safe BASE_MODEL when unset.
# Orin Nano ~8GB unified memory often cannot load 7B or even 3B (cudaMalloc OOM).
set -euo pipefail

if [[ -n "${BASE_MODEL:-}" ]]; then
  echo "$BASE_MODEL"
  exit 0
fi

model_name="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
if echo "$model_name" | grep -qi 'orin nano'; then
  # 1.5B Q4 ≈ 1GB — realistic on Orin Nano after OS/desktop overhead
  echo "qwen2.5-coder:1.5b"
elif [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; then
  echo "qwen2.5-coder:3b"
else
  echo "qwen2.5-coder:7b"
fi
