#!/usr/bin/env bash
# One-shot Jetson bootstrap for Autocode overnight machine.
# Safe to re-run. Does not create Notion databases or run interactive auth for you.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

SKIP_SWAP=0
SKIP_MAXN=0
SKIP_TAILSCALE=0
SKIP_CLONE=0

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap_jetson.sh [options]

Ordered Jetson setup for Autocode:
  1. Dependency check
  2. Data SSD layout (models / workspaces / swap on big disk)
  3. Swap (16G default on SSD)
  4. MAXN SUPER power mode (Jetson)
  5. .env from .env.example (if missing)
  6. Ollama + coder-64k model (into OLLAMA_MODELS)
  7. Hermes install + local-primary config
  8. Hermes smoke test
  9. GitHub CLI install
 10. Optional Tailscale install
 11. Clone WORKSPACE_REPOS (if configured)
 12. Doctor report

Options:
  --skip-swap         Do not create/enable swap
  --skip-maxn         Do not change nvpmodel
  --skip-tailscale    Do not install Tailscale
  --skip-clone        Do not clone WORKSPACE_REPOS
  -y, --yes           Non-interactive (accepted for compatibility)
  -h, --help          Show help

After this script:
  - Fill Notion + webhook values in .env
  - Run: gh auth login
  - Run: sudo tailscale up   (if using Tailscale)
  - Run: scripts/demo_night.sh
  - Then one supervised live night before enabling the timer
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-swap) SKIP_SWAP=1; shift ;;
    --skip-maxn) SKIP_MAXN=1; shift ;;
    --skip-tailscale) SKIP_TAILSCALE=1; shift ;;
    --skip-clone) SKIP_CLONE=1; shift ;;
    -y|--yes) shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

step() {
  echo
  echo "============================================================"
  echo "▶ $1"
  echo "============================================================"
}

step "1/12 Dependency check"
bash "${ROOT_DIR}/scripts/setup.sh" --check || true

step "2/12 Data SSD layout (4TB-friendly)"
bash "${ROOT_DIR}/bootstrap/05_use_data_ssd.sh" || {
  echo "WARN: data SSD layout skipped — using defaults under /opt."
}
# shellcheck disable=SC1091
source "${ROOT_DIR}/.env" 2>/dev/null || true

step "3/12 Swap (on SSD when AUTOCODE_DATA_ROOT is set)"
if [[ "${SKIP_SWAP}" -eq 1 ]]; then
  echo "Skipped (--skip-swap)."
else
  if [[ "$(id -u)" -eq 0 ]]; then
    bash "${ROOT_DIR}/bootstrap/01_setup_swap.sh" || {
      echo "WARN: swap step failed. Continuing."
    }
  else
    echo "Swap needs root. Run after bootstrap:"
    echo "  sudo SWAPFILE=\${SWAPFILE:-/swapfile} ./bootstrap/01_setup_swap.sh \${AUTOCODE_SWAP_GB:-16}"
  fi
fi

step "4/12 MAXN SUPER"
if [[ "${SKIP_MAXN}" -eq 1 ]]; then
  echo "Skipped (--skip-maxn)."
else
  bash "${ROOT_DIR}/bootstrap/02_enable_maxn.sh" || {
    echo "WARN: MAXN step skipped/failed (normal on non-Jetson hosts)."
  }
fi

step "5/12 Environment file"
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
  echo "Created .env from .env.example — edit secrets before a live night."
else
  echo ".env already exists."
fi

if ! grep -q '^AUTOCODE_AUTOPILOT_ENABLED=' "${ROOT_DIR}/.env"; then
  echo 'AUTOCODE_AUTOPILOT_ENABLED=0' >> "${ROOT_DIR}/.env"
fi

step "6/12 Ollama + coder-64k (models → OLLAMA_MODELS / SSD)"
# Ensure Ollama writes weights to the data SSD when configured.
if [[ -n "${OLLAMA_MODELS:-}" ]]; then
  mkdir -p "${OLLAMA_MODELS}"
  export OLLAMA_MODELS
  echo "OLLAMA_MODELS=$OLLAMA_MODELS"
fi
bash "${ROOT_DIR}/ollama/install_ollama_jetson.sh" || {
  echo "WARN: Ollama install failed. Install manually, then re-run."
}
# shellcheck disable=SC1091
source "${ROOT_DIR}/.env" 2>/dev/null || true
[[ -n "${OLLAMA_MODELS:-}" ]] && export OLLAMA_MODELS
bash "${ROOT_DIR}/ollama/create_coder_64k.sh" || {
  echo "WARN: model create failed (Ollama may still be starting). Retry later:"
  echo "  bash ollama/create_coder_64k.sh"
}

step "7/12 Hermes install"
bash "${ROOT_DIR}/hermes/install_hermes.sh"

step "8/12 Hermes local-primary config"
bash "${ROOT_DIR}/hermes/configure_local_primary.sh"

step "9/12 Hermes smoke"
if bash "${ROOT_DIR}/scripts/smoke_hermes.sh"; then
  echo "Hermes smoke OK."
else
  echo "WARN: Hermes smoke failed. Fix before a live night."
fi

step "10/12 GitHub CLI"
bash "${ROOT_DIR}/bootstrap/03_install_gh.sh" || {
  echo "WARN: gh install failed."
}

step "11/12 Tailscale (optional)"
if [[ "${SKIP_TAILSCALE}" -eq 1 ]]; then
  echo "Skipped (--skip-tailscale)."
else
  bash "${ROOT_DIR}/bootstrap/04_install_tailscale.sh" || {
    echo "WARN: Tailscale install failed/skipped."
  }
fi

step "12/12 Clone workspaces + doctor"
if [[ "${SKIP_CLONE}" -eq 1 ]]; then
  echo "Clone skipped (--skip-clone)."
else
  bash "${ROOT_DIR}/scripts/clone_workspaces.sh" || {
    echo "WARN: clone skipped (set WORKSPACE_REPOS + gh auth)."
  }
fi

bash "${ROOT_DIR}/scripts/doctor.sh" || true

cat <<'EOF'

============================================================
Bootstrap finished (or as far as this host allows).
============================================================

Remaining operator steps:

  Prefer one-shot:  ./scripts/go_live.sh --local-only --first-night --enable-autopilot

  Or manually:
  1. Edit .env — Notion token + NOTION_HUB_PAGE (or DB ids), webhook URLs
  2. ./scripts/auth_github.sh   # or: gh auth login
  3. sudo SWAPFILE=... ./bootstrap/01_setup_swap.sh 16   # if swap not rooted yet
  4. sudo tailscale up          # if installed
  5. ./scripts/demo_night.sh
  6. ./cron/overnight_run.sh --force
  7. AUTOCODE_AUTOPILOT_ENABLED=1 + ./cron/install_autopilot_timers.sh

With a 4TB SSD, models/workspaces/swap live under AUTOCODE_DATA_ROOT
(see bootstrap/05_use_data_ssd.sh).

Remote ops:
  scripts/status.sh
  scripts/control.sh pause|resume|abort|skip <task_id>

Docs: docs/go-live.md
EOF
