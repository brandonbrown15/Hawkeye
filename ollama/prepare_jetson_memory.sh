#!/usr/bin/env bash
# Free Jetson unified memory before loading a coder model.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Jetson memory prep =="
echo "device: $(tr -d '\0' </proc/device-tree/model 2>/dev/null || uname -m)"
free -h || true
echo

# Only one ollama daemon; stop loaded models so VRAM/unified mem is released.
if command -v ollama >/dev/null 2>&1; then
  ollama ps 2>/dev/null || true
  # Stop every loaded model (best-effort)
  while read -r name; do
    [[ -z "$name" || "$name" == "NAME" ]] && continue
    echo "Stopping loaded model: $name"
    ollama stop "$name" 2>/dev/null || true
  done < <(ollama ps 2>/dev/null | awk 'NR>1{print $1}')
fi

# Drop page cache if we can (helps fragmented unified memory a bit)
if [[ "$(id -u)" -eq 0 ]]; then
  sync
  echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true
elif command -v sudo >/dev/null 2>&1; then
  sudo sh -c 'sync; echo 3 >/proc/sys/vm/drop_caches' 2>/dev/null || true
fi

sleep 1
echo
free -h || true
avail_kb="$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)"
echo "MemAvailable: ${avail_kb} kB"
if [[ "${avail_kb:-0}" -lt 2500000 ]]; then
  echo "WARN: <~2.5GB MemAvailable — even 3B may CUDA-OOM. Close browsers/UI, then retry."
  echo "  systemctl --user stop hawkeye-ui.service 2>/dev/null || true"
fi
