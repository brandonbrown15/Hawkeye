"""Per-user Hawkeye profiles (name + employee number).

Password hashes stay in config/users.json. Profile fields live under
$AUTOCODE_DATA_ROOT/hawkeye/accounts/profiles.json (or state fallback).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from ui import auth as ui_auth

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None


def accounts_root() -> Path:
    raw = os.environ.get("HAWKEYE_ACCOUNTS_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        data = Path(os.environ.get("AUTOCODE_DATA_ROOT", "")).expanduser()
        if str(data):
            path = data / "hawkeye" / "accounts"
        else:
            path = ROOT / "state" / "hawkeye-accounts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_path() -> Path:
    return accounts_root() / "profiles.json"


def _load_unlocked() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    path = profiles_path()
    data: dict[str, Any] = {"profiles": {}}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                profiles = raw.get("profiles", raw)
                if isinstance(profiles, dict):
                    data = {"profiles": profiles}
        except (OSError, json.JSONDecodeError):
            pass
    _CACHE = data
    return dict(data)


def clear_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None


def _save_unlocked(data: dict[str, Any]) -> None:
    global _CACHE
    path = profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _CACHE = data


def get_profile(email: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load_unlocked()
        row = (data.get("profiles") or {}).get(email) or {}
    return {
        "email": email,
        "first_name": str(row.get("first_name") or ""),
        "last_name": str(row.get("last_name") or ""),
        "employee_number": str(row.get("employee_number") or ""),
        "display_name": _display_name(email, row),
        "updated_at": row.get("updated_at"),
        "profile_complete": bool(
            str(row.get("first_name") or "").strip()
            and str(row.get("last_name") or "").strip()
            and str(row.get("employee_number") or "").strip()
        ),
    }


def update_profile(
    email: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    employee_number: str | None = None,
) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    if not email or not ui_auth.is_allowed_email(email):
        raise ValueError("email must be on the allowed work domain")
    with _LOCK:
        data = _load_unlocked()
        profiles = dict(data.get("profiles") or {})
        row = dict(profiles.get(email) or {})
        if first_name is not None:
            row["first_name"] = first_name.strip()
        if last_name is not None:
            row["last_name"] = last_name.strip()
        if employee_number is not None:
            row["employee_number"] = employee_number.strip()
        row["updated_at"] = time.time()
        profiles[email] = row
        data["profiles"] = profiles
        _save_unlocked(data)
    return get_profile(email)


def list_directory() -> list[dict[str, Any]]:
    """Coworker directory (no password hashes)."""
    users = ui_auth.load_users()
    out: list[dict[str, Any]] = []
    for email in sorted(users.keys()):
        out.append(get_profile(email))
    return out


def _display_name(email: str, row: dict[str, Any]) -> str:
    first = str(row.get("first_name") or "").strip()
    last = str(row.get("last_name") or "").strip()
    if first or last:
        return f"{first} {last}".strip()
    return email.split("@", 1)[0]
