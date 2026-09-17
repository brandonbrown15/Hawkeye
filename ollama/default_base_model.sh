#!/usr/bin/env bash
# Echo a Jetson-safe BASE_MODEL when unset.
# Orin Nano ~8GB unified memory cannot reliably load qwen2.5-coder:7b (CUDA OOM).
set -euo pipefail

if [[ -n "${BASE_MODEL:-}" ]]; then
  echo "$BASE_MODEL"
  exit 0
fi

if [[ -f /etc/nv_tegra_release ]] || [[ "$(uname -m)" == "aarch64" ]]; then
  # 3B Q4 ≈ 2GB — fits Orin Nano; override with BASE_MODEL=qwen2.5-coder:7b if you have AGX/32GB+
  echo "qwen2.5-coder:3b"
else
  echo "qwen2.5-coder:7b"
fi
