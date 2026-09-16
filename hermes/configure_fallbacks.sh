#!/usr/bin/env bash
# Phase 2b — document/configure paid fallbacks only after local Hermes works.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

echo "== Hermes fallbacks (optional) =="
echo "Policy: local first. Paid models are exceptions (Cloud-only, explicit Model route, or 2 local fails)."
echo
echo "Configure via: hermes fallback"
echo "Or merge fallback_providers into Hermes config after setting:"
echo "  ANTHROPIC_API_KEY (Claude)"
echo "  OPENROUTER_API_KEY / XAI_API_KEY (optional Grok)"
echo
if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENROUTER_API_KEY:-}" && -z "${XAI_API_KEY:-}" ]]; then
  echo "No paid keys in .env — skipping active fallback wiring (expected for early setup)."
  exit 0
fi

echo "Keys detected in environment. Run \`hermes fallback\` interactively on the Jetson to register them."
