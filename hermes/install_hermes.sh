#!/usr/bin/env bash
# Install Hermes Agent (Nous Research) for real — fails if hermes is still missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Install Hermes Agent =="

if command -v hermes >/dev/null 2>&1; then
  echo "hermes already on PATH: $(command -v hermes)"
  hermes --version 2>/dev/null || hermes version 2>/dev/null || true
else
  echo "Installing via official Nous installer (--skip-setup)…"
  # Ref: https://hermes-agent.nousresearch.com/docs/getting-started/quickstart
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup

  # Common install locations — ensure current shell can see hermes
  export PATH="${HOME}/.local/bin:${HOME}/.hermes/bin:/usr/local/bin:${PATH}"
  # shellcheck disable=SC1090
  [[ -f "${HOME}/.bashrc" ]] && source "${HOME}/.bashrc" 2>/dev/null || true

  if ! command -v hermes >/dev/null 2>&1; then
    # Fallback: pip/uv user install
    echo "Official installer did not put hermes on PATH — trying pip…"
    python3 -m pip install --user 'hermes-agent' 2>/dev/null \
      || pip3 install --user 'hermes-agent' 2>/dev/null \
      || true
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "FAIL: hermes not found after install."
  echo "Try manually:"
  echo "  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
  echo "  # or: ollama launch hermes"
  echo "Then re-run: ./hermes/install_hermes.sh"
  exit 1
fi

echo "OK hermes=$(command -v hermes)"
hermes doctor 2>/dev/null || hermes --help >/dev/null || true
echo "Next: ./hermes/configure_local_primary.sh"
