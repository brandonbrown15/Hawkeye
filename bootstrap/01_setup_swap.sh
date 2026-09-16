#!/usr/bin/env bash
# Swapfile helper. Prefer the data SSD when SWAPFILE / AUTOCODE_DATA_ROOT is set.
# With a multi-TB NVMe, 16G swap is a good default for big coder contexts.
#
#   sudo ./bootstrap/01_setup_swap.sh
#   sudo SWAPFILE=/mnt/nvme/autocode/swap/autocode.swap ./bootstrap/01_setup_swap.sh 16
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

SIZE_GB="${1:-${AUTOCODE_SWAP_GB:-16}}"
SWAPFILE="${SWAPFILE:-/swapfile}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0 [$SIZE_GB]"
  echo "Tip: after ./bootstrap/05_use_data_ssd.sh, SWAPFILE points at your SSD."
  exit 1
fi

if swapon --show | grep -qF "$SWAPFILE"; then
  echo "Swap already active at $SWAPFILE:"
  swapon --show
  exit 0
fi

mkdir -p "$(dirname "$SWAPFILE")"
fallocate -l "${SIZE_GB}G" "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1G count="$SIZE_GB"
chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE"
swapon "$SWAPFILE"

if ! grep -qF "$SWAPFILE" /etc/fstab; then
  echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
fi

echo "Swap ${SIZE_GB}G enabled at $SWAPFILE"
