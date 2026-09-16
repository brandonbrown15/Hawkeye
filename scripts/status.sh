#!/usr/bin/env bash
# Live status for remote monitoring (run via Tailscale SSH).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
cd "$ROOT"
exec python3 -m orchestrator.ops status
