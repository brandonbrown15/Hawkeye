#!/usr/bin/env bash
# Install / repair Ollama on Jetson (JetPack 6.x / aarch64).
# The CLI alone is not enough — inference needs lib/ollama/llama-server
# (bundled by the official installer + jetpack6 overlay).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Install Ollama (Jetson) =="

find_llama_server() {
  local d
  for d in /usr/local/lib/ollama /usr/lib/ollama; do
    if [[ -x "$d/llama-server" ]]; then
      echo "$d/llama-server"
      return 0
    fi
  done
  # Newer layouts nest under cuda_* dirs
  local hit
  hit="$(find /usr/local/lib/ollama /usr/lib/ollama -type f -name llama-server 2>/dev/null | head -1 || true)"
  if [[ -n "$hit" && -x "$hit" ]]; then
    echo "$hit"
    return 0
  fi
  return 1
}

ollama_bin() {
  if [[ -x /usr/local/bin/ollama ]]; then
    echo /usr/local/bin/ollama
  elif [[ -x /usr/bin/ollama ]]; then
    echo /usr/bin/ollama
  else
    command -v ollama
  fi
}

NEED_INSTALL=0
if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama CLI missing"
  NEED_INSTALL=1
elif ! find_llama_server >/dev/null; then
  echo "WARN: ollama CLI present ($(ollama --version 2>/dev/null || true)) but llama-server runner missing"
  echo "      Inference will HTTP 500 until the JetPack runner package is installed."
  NEED_INSTALL=1
else
  echo "ollama OK: $(ollama --version 2>/dev/null || true)"
  echo "runner: $(find_llama_server)"
fi

if [[ "$NEED_INSTALL" -eq 1 ]] || [[ "${OLLAMA_FORCE_REINSTALL:-0}" == "1" ]]; then
  echo "Running official installer (includes linux-arm64 + jetpack overlay on Tegra)…"
  # Stop any half-broken daemon first
  sudo systemctl stop ollama 2>/dev/null || true
  pkill -f '[o]llama serve' 2>/dev/null || true
  curl -fsSL https://ollama.com/install.sh | sh

  if ! find_llama_server >/dev/null; then
    echo "WARN: llama-server still missing after install.sh — trying JetPack overlay tarball…"
    ARCH=arm64
    DEST=/usr/local
    if [[ -f /etc/nv_tegra_release ]] && grep -q R36 /etc/nv_tegra_release; then
      PKG="ollama-linux-${ARCH}-jetpack6"
    elif [[ -f /etc/nv_tegra_release ]] && grep -q R35 /etc/nv_tegra_release; then
      PKG="ollama-linux-${ARCH}-jetpack5"
    else
      PKG="ollama-linux-${ARCH}"
    fi
    TMP="$(mktemp -d)"
    echo "Downloading ${PKG}.tgz …"
    if curl -fsSL "https://ollama.com/download/${PKG}.tgz" -o "$TMP/${PKG}.tgz"; then
      sudo mkdir -p "$DEST/lib/ollama" "$DEST/bin"
      sudo tar -xzf "$TMP/${PKG}.tgz" -C "$DEST"
      # Some archives nest contents; flatten common layouts
      if [[ ! -x "$DEST/lib/ollama/llama-server" ]]; then
        hit="$(find "$TMP" "$DEST" -type f -name llama-server 2>/dev/null | head -1 || true)"
        if [[ -n "$hit" ]]; then
          sudo mkdir -p "$DEST/lib/ollama"
          sudo cp -f "$hit" "$DEST/lib/ollama/llama-server"
          sudo chmod 755 "$DEST/lib/ollama/llama-server"
        fi
      fi
    else
      echo "FAIL: could not download ${PKG}.tgz"
    fi
    rm -rf "$TMP"
  fi
fi

if ! find_llama_server >/dev/null; then
  cat <<'EOF'
FAIL: llama-server still not installed.

Checked: /usr/local/lib/ollama/llama-server, /usr/lib/ollama/**

Recovery options:
  1) Force reinstall:
       OLLAMA_FORCE_REINSTALL=1 ./ollama/install_ollama_jetson.sh
  2) Official one-liner as root:
       curl -fsSL https://ollama.com/install.sh | sh
  3) Jetson AI Lab container (JetPack 6 Orin):
       docker run --runtime nvidia -d --network host --name ollama \
         -v "$OLLAMA_MODELS:/ollama" -e OLLAMA_MODELS=/ollama \
         dustynv/ollama:r36.2.0
     Docs: https://www.jetson-ai-lab.com/tutorials/ollama/

EOF
  exit 1
fi

echo "runner OK: $(find_llama_server)"

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

# Prefer the installed binary (not a stray PATH copy)
export PATH="/usr/local/bin:/usr/bin:${PATH}"
OLLAMA_BIN="$(ollama_bin)"
echo "Using: $OLLAMA_BIN"

# Wait until the API answers (systemd or background serve).
bash "$ROOT/ollama/ensure_ollama.sh" || {
  echo "WARN: Ollama API not up yet. Later: ./ollama/ensure_ollama.sh --restart"
}

echo "Smoke: curl http://127.0.0.1:11434/api/tags"
curl -fsS "http://127.0.0.1:11434/api/tags" | head -c 400 || true
echo
echo "Done. Next: ./ollama/create_coder_64k.sh"
