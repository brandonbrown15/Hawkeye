#!/usr/bin/env bash
# Install Ollama on Jetson (JetPack 6.x / aarch64). Prefer NVIDIA/Jetson-capable builds when available.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Install Ollama =="

if command -v ollama >/dev/null; then
  echo "ollama already installed: $(ollama --version 2>/dev/null || true)"
else
  curl -fsSL https://ollama.com/install.sh | sh
fi

# Keep model warm for overnight runs
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-24h}"
OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-65536}"

mkdir -p "$HOME/.config/systemd/user" /etc/systemd/system 2>/dev/null || true

# Prefer a drop-in if ollama.service exists system-wide
if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  sudo tee /etc/systemd/system/ollama.service.d/autocode.conf >/dev/null <<EOF
[Service]
Environment="OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE}"
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_CONTEXT_LENGTH=${OLLAMA_NUM_CTX}"
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now ollama
else
  echo "Start Ollama manually: OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE} OLLAMA_HOST=127.0.0.1:11434 ollama serve"
fi

echo "Smoke: curl http://127.0.0.1:11434/api/tags"
curl -fsS "http://127.0.0.1:11434/api/tags" | head -c 400 || true
echo
echo "Done. Next: ./ollama/create_coder_64k.sh"
