#!/usr/bin/env bash
# End-to-end simulation of an overnight Autocode run (no Notion/Hermes required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Autocode demo night =="
python3 -m unittest tests.test_routing tests.test_orchestrator_mock -v
echo
python3 orchestrator/run_night.py --mock --limit 2
echo
echo "Mock Notion events:"
tail -n 20 state/mock_notion.jsonl 2>/dev/null || true
echo
echo "Latest digest:"
ls -1t state/digest-*.txt 2>/dev/null | head -1 | xargs -r cat
