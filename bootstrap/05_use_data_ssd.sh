#!/usr/bin/env bash
# Prefer a large data SSD/NVMe for Autocode heavy paths (models, workspaces, swap).
# Safe to re-run. Does not reformat disks — only creates directories + writes .env hints.
#
# Override mount/root explicitly:
#   AUTOCODE_DATA_ROOT=/mnt/nvme ./bootstrap/05_use_data_ssd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Autocode data SSD layout =="

pick_data_root() {
  if [[ -n "${AUTOCODE_DATA_ROOT:-}" ]]; then
    echo "${AUTOCODE_DATA_ROOT}"
    return
  fi

  # Prefer common Jetson NVMe mount points if they exist and have plenty of free space.
  local cand
  for cand in /mnt/nvme /mnt/ssd /data /opt/data /media/ssd; do
    if [[ -d "$cand" ]] && [[ -w "$cand" || "$(id -u)" -eq 0 ]]; then
      local free_gb
      free_gb="$(df -BG --output=avail "$cand" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)"
      if [[ "${free_gb:-0}" -ge 100 ]]; then
        echo "$cand"
        return
      fi
    fi
  done

  # Auto-detect largest mounted non-tmpfs filesystem with >=100GB free.
  local best="" best_free=0
  while read -r mp free; do
    free="${free%G}"
    free="${free%.*}"
    [[ -z "$free" ]] && continue
    [[ "$mp" == "/" ]] && continue
    [[ "$mp" == /boot* ]] && continue
    [[ "$mp" == /snap* ]] && continue
    [[ "$mp" == /run* ]] && continue
    if [[ "$free" -ge 100 && "$free" -gt "$best_free" ]]; then
      best_free="$free"
      best="$mp"
    fi
  done < <(df -BG --output=target,avail 2>/dev/null | tail -n +2 | awk '{print $1, $2}')

  if [[ -n "$best" ]]; then
    echo "$best/autocode"
    return
  fi

  # Fallback: root disk (still works; just not ideal)
  echo "/opt/autocode-data"
}

DATA_ROOT="$(pick_data_root)"
echo "DATA_ROOT=$DATA_ROOT"

mkdir -p \
  "$DATA_ROOT/workspaces" \
  "$DATA_ROOT/ollama" \
  "$DATA_ROOT/models" \
  "$DATA_ROOT/swap" \
  "$DATA_ROOT/logs" \
  "$DATA_ROOT/hermes" \
  "$DATA_ROOT/state" \
  "$DATA_ROOT/hawkeye/memory" || {
  echo "Need write access to $DATA_ROOT (try: sudo mkdir -p $DATA_ROOT && sudo chown \"\$USER\": \"\$DATA_ROOT\")"
  exit 1
}

free_gb="$(df -BG --output=avail "$DATA_ROOT" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)"
echo "Free on data root: ${free_gb}G"

# Upsert .env keys
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || cp "$ROOT/.env.example" "$ENV_FILE"

upsert() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    grep -v "^${key}=" "$ENV_FILE" >"${ENV_FILE}.tmp" || true
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
  fi
  echo "${key}=${val}" >>"$ENV_FILE"
}

upsert AUTOCODE_DATA_ROOT "$DATA_ROOT"
upsert WORKSPACE_ROOT "$DATA_ROOT/workspaces"
upsert OLLAMA_MODELS "$DATA_ROOT/ollama"
upsert AUTOCODE_LOG_DIR "$DATA_ROOT/logs"
upsert AUTOCODE_STATE_DIR "$DATA_ROOT/state"
upsert HERMES_CONFIG_DIR "$DATA_ROOT/hermes"
upsert SWAPFILE "$DATA_ROOT/swap/autocode.swap"
upsert HAWKEYE_MEMORY_DIR "$DATA_ROOT/hawkeye/memory"
upsert HAWKEYE_MEMORY_ENABLED "${HAWKEYE_MEMORY_ENABLED:-1}"
upsert HAWKEYE_RESEARCH_ENABLED "${HAWKEYE_RESEARCH_ENABLED:-1}"

# With a multi-TB SSD, 16–32G swap is cheap insurance for big coder ctx.
if [[ "${free_gb:-0}" -ge 500 ]]; then
  upsert AUTOCODE_SWAP_GB "${AUTOCODE_SWAP_GB:-16}"
else
  upsert AUTOCODE_SWAP_GB "${AUTOCODE_SWAP_GB:-8}"
fi

# Persist Ollama models on the SSD for future shells / systemd.
# Users may also set this in ollama.service.d — bootstrap docs mention it.
if ! grep -q 'OLLAMA_MODELS' "$HOME/.bashrc" 2>/dev/null; then
  echo "export OLLAMA_MODELS=\"$DATA_ROOT/ollama\"" >>"$HOME/.bashrc"
fi
export OLLAMA_MODELS="$DATA_ROOT/ollama"
mkdir -p "$OLLAMA_MODELS"

cat <<EOF

SSD layout ready under $DATA_ROOT:
  workspaces/  → WORKSPACE_ROOT
  ollama/      → OLLAMA_MODELS (large coder weights live here)
  hawkeye/memory/ → HAWKEYE_MEMORY_DIR (private vector memory; never public Autocode)
  swap/        → SWAPFILE (see bootstrap/01_setup_swap.sh)
  logs/ state/ hermes/

Next:
  sudo SWAPFILE=$DATA_ROOT/swap/autocode.swap ./bootstrap/01_setup_swap.sh \${AUTOCODE_SWAP_GB:-16}
  # optional systemd drop-in so Ollama keeps using the SSD after reboot:
  #   Environment=OLLAMA_MODELS=$DATA_ROOT/ollama
EOF
