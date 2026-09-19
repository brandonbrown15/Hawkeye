#!/usr/bin/env python3
"""Add or update a @brownhawke.engineering Hawkeye login (password hash only).

Preferred spelling:
  ./scripts/hawkeye accounts set-password --email mark@brownhawke.engineering
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui.accounts_cli import main  # noqa: E402


if __name__ == "__main__":
    # Historical flags: --email --password --users-file
    raise SystemExit(main(["set-password", *sys.argv[1:]]))
