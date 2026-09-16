#!/usr/bin/env python3
"""Add or update a @brownhawke.engineering Hawkeye login (password hash only)."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import auth as ui_auth  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Create/update Hawkeye work email login")
    parser.add_argument("--email", required=True, help="Work email, e.g. brandon@brownhawke.engineering")
    parser.add_argument("--password", help="Password (prompted if omitted)")
    parser.add_argument(
        "--users-file",
        default=str(ui_auth.users_file_path()),
        help="Path to config/users.json",
    )
    args = parser.parse_args()

    email = ui_auth.normalize_email(args.email)
    if "@" not in email:
        email = f"{email}@{ui_auth.allowed_email_domain()}"
    if not ui_auth.is_allowed_email(email):
        raise SystemExit(
            f"Email must end with @{ui_auth.allowed_email_domain()} (got {email!r})"
        )

    pw = args.password or getpass.getpass("Password: ")
    if len(pw) < 8:
        raise SystemExit("Use at least 8 characters")

    digest = ui_auth.hash_password(pw)
    path = Path(args.users_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"allowed_domain": ui_auth.allowed_email_domain(), "users": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
                data.setdefault("users", {})
        except json.JSONDecodeError:
            pass
    users = data.setdefault("users", {})
    users[email] = digest
    data["allowed_domain"] = ui_auth.allowed_email_domain()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    ui_auth.clear_users_cache()

    print(f"Updated {path}")
    print(f"Login email: {email}")
    print("Password hash stored (plaintext password was not written).")
    print("\nAlso ensure .env has:")
    print("AUTOCODE_PRIVATE_MODE=1")
    print(f"HAWKEYE_ALLOWED_EMAIL_DOMAIN={ui_auth.allowed_email_domain()}")
    print(f"HAWKEYE_USERS_FILE={path}")
    print("AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering")
    print("AUTOCODE_UI_SECURE=1")


if __name__ == "__main__":
    main()
