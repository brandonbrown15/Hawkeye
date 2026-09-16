#!/usr/bin/env bash
# Phase 0 smoke checks for Jetson Orin Nano Super.
# Does not flash JetPack — verifies an already-booted machine.
set -euo pipefail

echo "== Autocode bootstrap: Jetson checks =="

fail=0
check() {
  local label="$1"
  shift
  if "$@"; then
    echo "  OK  $label"
  else
    echo "  FAIL $label"
    fail=1
  fi
}

check "aarch64" bash -c '[[ "$(uname -m)" == "aarch64" ]]'
check "rootfs readable" test -r /etc/nv_tegra_release -o -r /etc/nvidia-container-runtime/host-files-for-container.d
check "nvme present or root on nvme" bash -c 'lsblk -d -o NAME,TRAN 2>/dev/null | grep -qi nvme || findmnt -n -o SOURCE / | grep -qi nvme'
check "ssh server" bash -c 'systemctl is-active --quiet ssh || systemctl is-active --quiet sshd'
check "nvpmodel available" command -v nvpmodel >/dev/null

if command -v nvpmodel >/dev/null; then
  echo "  info nvpmodel modes:"
  nvpmodel -q 2>/dev/null || true
  echo "  tip  Select MAXN_SUPER when available: sudo nvpmodel -m <maxn_super_id>"
fi

if [[ -f /proc/meminfo ]]; then
  swap_kb=$(awk '/SwapTotal/ {print $2}' /proc/meminfo)
  echo "  info SwapTotal=${swap_kb} kB (target ~4–8 GB)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "One or more checks failed. Fix hardware/OS before Phase 1."
  exit 1
fi

echo "Phase 0 checks passed."
