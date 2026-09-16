#!/usr/bin/env bash
# Kid-simple Notion connect: open browser → Allow → done.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python3 "$ROOT/scripts/connect_notion.py" "$@"
