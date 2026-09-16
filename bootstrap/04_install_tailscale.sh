#!/usr/bin/env bash
# Install Tailscale for remote SSH monitoring/intervene from phone/laptop.
set -euo pipefail

echo "== Install Tailscale =="

if command -v tailscale >/dev/null 2>&1; then
  echo "tailscale already installed"
else
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo
if tailscale status >/dev/null 2>&1; then
  echo "OK: Tailscale already up"
  tailscale status | head -20
else
  echo "Next (interactive on the Jetson):"
  echo "  sudo tailscale up"
  echo "Then from your laptop/phone: ssh <jetson-tailscale-name>"
  echo "Docs: docs/remote-ops.md"
fi
