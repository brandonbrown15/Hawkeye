#!/usr/bin/env python3
"""Hawkeye account admin CLI (password hashes only — never writes plaintext).

Usage:
  ./scripts/hawkeye accounts set-password --email mark@brownhawke.engineering
  ./scripts/hawkeye accounts list
  ./scripts/hawkeye accounts check --email mark@brownhawke.engineering
  python3 -m ui.accounts_cli accounts set-password --email mark
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import auth as ui_auth  # noqa: E402


def _bind_users_file(path: str | None) -> None:
    if path:
        os.environ["HAWKEYE_USERS_FILE"] = path
        ui_auth.clear_users_cache()


def _prompt_password(*, confirm: bool) -> str:
    pw = getpass.getpass("New password: ")
    if confirm:
        again = getpass.getpass("Confirm password: ")
        if pw != again:
            raise SystemExit("Passwords did not match")
    return pw


def cmd_set_password(args: argparse.Namespace) -> int:
    _bind_users_file(args.users_file)
    email = ui_auth.canonicalize_email(args.email)
    if not ui_auth.is_allowed_email(email):
        raise SystemExit(
            f"Email must end with @{ui_auth.allowed_email_domain()} (got {email!r})"
        )
    pw = args.password or _prompt_password(confirm=not args.password)
    try:
        result = ui_auth.upsert_user_password(email, pw, users_file=Path(args.users_file))
    except ValueError as e:
        raise SystemExit(str(e)) from e

    action = "Created" if result["created"] else "Updated"
    print(f"{action} login for {result['email']}")
    print(f"Users file: {result['path']}")
    print("Password hash stored (plaintext password was not written).")
    print("Known work emails:", ", ".join(result["users"]) or "(none)")
    print()
    print("The running UI reloads users.json when the file mtime changes.")
    print("If sign-in still fails:")
    print("  systemctl --user restart hawkeye-ui.service")
    print()
    print("Also ensure .env has:")
    print("AUTOCODE_PRIVATE_MODE=1")
    print(f"HAWKEYE_ALLOWED_EMAIL_DOMAIN={ui_auth.allowed_email_domain()}")
    print(f"HAWKEYE_USERS_FILE={result['path']}")
    print("AUTOCODE_PUBLIC_HOST=hawkeye.brownhawke.engineering")
    print("AUTOCODE_UI_SECURE=1")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    _bind_users_file(args.users_file)
    emails = ui_auth.list_login_emails()
    path = ui_auth.users_file_path()
    print(f"Users file: {path}")
    print(f"Allowed domain: @{ui_auth.allowed_email_domain()}")
    if not emails:
        print("No work logins configured.")
        return 0
    for email in emails:
        print(email)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    _bind_users_file(args.users_file)
    email = ui_auth.canonicalize_email(args.email)
    pw = args.password or getpass.getpass("Password: ")
    failure = ui_auth.diagnose_login(email, pw)
    if failure:
        print(f"FAIL {failure.code}: {failure.error}")
        if failure.hint:
            print(failure.hint)
        return 1
    print(f"OK {email} — password matches the users file.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hawkeye",
        description="Hawkeye admin CLI (accounts / passwords). Never prints or stores plaintext passwords.",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    accounts = sub.add_parser("accounts", help="Create, list, or verify work-email logins")
    acct = accounts.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--users-file",
        default=str(ui_auth.users_file_path()),
        help="Path to config/users.json",
    )

    set_pw = acct.add_parser(
        "set-password",
        parents=[common],
        help="Create or reset a work-email password (hash only)",
    )
    set_pw.add_argument("--email", required=True, help="Work email, e.g. mark@brownhawke.engineering")
    set_pw.add_argument("--password", help="Password (prompted if omitted — prefer omit so it is not in shell history)")
    set_pw.set_defaults(func=cmd_set_password)

    listed = acct.add_parser("list", parents=[common], help="Print configured work emails (no hashes)")
    listed.set_defaults(func=cmd_list)

    check = acct.add_parser("check", parents=[common], help="Verify an email+password against the users file")
    check.add_argument("--email", required=True)
    check.add_argument("--password", help="Password (prompted if omitted)")
    check.set_defaults(func=cmd_check)

    # Also accept `python3 -m ui.accounts_cli set-password` without the accounts group.
    top_set = sub.add_parser(
        "set-password",
        parents=[common],
        help="Alias for accounts set-password",
    )
    top_set.add_argument("--email", required=True)
    top_set.add_argument("--password")
    top_set.set_defaults(func=cmd_set_password)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
