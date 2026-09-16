#!/usr/bin/env python3
"""Hash a password for Hawkeye / AUTOCODE_PRIVATE_PASSWORD_HASH."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui.auth import hash_password  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Hawkeye private password hash")
    parser.add_argument("--password", help="Password (prompted if omitted)")
    parser.add_argument("--user", default="brown", help="Username to print in .env hint")
    args = parser.parse_args()
    pw = args.password or getpass.getpass("Password: ")
    if len(pw) < 8:
        raise SystemExit("Use at least 8 characters")
    digest = hash_password(pw)
    print(digest)
    print("\nAdd to .env:")
    print("AUTOCODE_PRODUCT_NAME=Hawkeye")
    print("AUTOCODE_PRIVATE_MODE=1")
    print(f"AUTOCODE_PRIVATE_USER={args.user}")
    print(f"AUTOCODE_PRIVATE_PASSWORD_HASH={digest}")
    print("# Local is free all day; Cursor/Grok escalate hard work (leave this 0)")
    print("AUTOCODE_PERSONAL_LOCAL_ONLY=0")
    print("AUTOCODE_LOCAL_ONLY=0")
    print("AUTOCODE_COST_PROFILE=cursor-grok")
    print("AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering")
    print("AUTOCODE_UI_SECURE=1")


if __name__ == "__main__":
    main()
