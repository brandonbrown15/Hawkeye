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
OLLAMA_NUM_CTX="$(bash "$ROOT/ollama/default_num_ctx.sh")"
export OLLAMA_NUM_CTX

mkdir -p "$HOME/.config/systemd/user" /etc/systemd/system 2>/dev/null || true

# Prefer a drop-in if ollama.service exists system-wide
if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  DROP_IN=$(cat <<EOF
[Service]
Environment="OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE}"
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_CONTEXT_LENGTH=${OLLAMA_NUM_CTX}"
EOF
)
  if [[ -n "${OLLAMA_MODELS:-}" ]]; then
    DROP_IN+=$'\n'"Environment=\"OLLAMA_MODELS=${OLLAMA_MODELS}\""
  fi
  printf '%s\n' "$DROP_IN" | sudo tee /etc/systemd/system/ollama.service.d/autocode.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now ollama || true
fi

# Wait until the API answers (systemd or background serve).
bash "$ROOT/ollama/ensure_ollama.sh" || {
  echo "WARN: Ollama API not up yet. Later: ./ollama/ensure_ollama.sh --restart"
}

echo "Smoke: curl http://127.0.0.1:11434/api/tags"
curl -fsS "http://127.0.0.1:11434/api/tags" | head -c 400 || true
echo
echo "Done. Next: ./ollama/create_coder_64k.sh"
