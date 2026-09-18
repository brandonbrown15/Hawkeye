"""Persisted runtime settings for Hawkeye UI (survives process restart).

Stored under state/hawkeye-runtime.json. Local-only is **per signed-in email**
so brandon@ and mark@ can choose independently. Env vars remain the default
when a user has no override.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None

# Synthetic key when private login is off (single shared UI session).
OPEN_USER = "__open__"


def runtime_path() -> Path:
    raw = os.environ.get("HAWKEYE_RUNTIME_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    state = Path(os.environ.get("AUTOCODE_STATE_DIR", "state")).expanduser()
    if not state.is_absolute():
        state = ROOT / state
    return state / "hawkeye-runtime.json"


def _env_bool(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes", "on")


def normalize_user(user: str | None) -> str | None:
    if user is None:
        return None
    email = (user or "").strip().lower()
    return email or None


def _load_unlocked() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    path = runtime_path()
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            data = {}
    # Ensure users map exists in memory view.
    if "users" not in data or not isinstance(data.get("users"), dict):
        data = dict(data)
        data["users"] = dict(data.get("users") or {}) if isinstance(data.get("users"), dict) else {}
    _CACHE = data
    return dict(data)


def load() -> dict[str, Any]:
    with _LOCK:
        return _load_unlocked()


def clear_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None


def _users_map(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("users")
    return dict(raw) if isinstance(raw, dict) else {}


def _user_row(data: dict[str, Any], user: str | None) -> dict[str, Any]:
    email = normalize_user(user)
    if not email:
        return {}
    row = _users_map(data).get(email)
    return dict(row) if isinstance(row, dict) else {}


def _personal_local_only_from(data: dict[str, Any], user: str | None) -> bool:
    """Resolve local-only for one account.

    Priority: per-user override → legacy global runtime key → env.
    Legacy global key keeps single-operator Jetsons working after upgrade.
    """
    row = _user_row(data, user)
    if "personal_local_only" in row:
        return bool(row["personal_local_only"])
    # Legacy (pre per-user) global flag — only when no per-user map entries yet,
    # or as fallback when this user has never toggled.
    users = _users_map(data)
    if "personal_local_only" in data and not users:
        return bool(data["personal_local_only"])
    if "personal_local_only" in data and normalize_user(user) and normalize_user(user) not in users:
        # User never set their own preference; do not inherit another operator's
        # legacy global after users map exists — fall through to env.
        pass
    return _env_bool("AUTOCODE_PERSONAL_LOCAL_ONLY", "0")


def _autopilot_local_only_from(data: dict[str, Any]) -> bool:
    """Overnight/worker routing — env / explicit global only (not per-user chat)."""
    if "local_only" in data:
        return bool(data["local_only"])
    return _env_bool("AUTOCODE_LOCAL_ONLY", "0")


def personal_local_only(user: str | None = None) -> bool:
    """True when this account's UI/chat must stay on the free local model."""
    with _LOCK:
        return _personal_local_only_from(_load_unlocked(), user)


def autopilot_local_only() -> bool:
    """True when overnight/worker routing should not require cloud delegates."""
    with _LOCK:
        return _autopilot_local_only_from(_load_unlocked())


def has_local_only_override(user: str | None = None) -> bool:
    with _LOCK:
        data = _load_unlocked()
        email = normalize_user(user)
        if email:
            row = _user_row(data, email)
            if "personal_local_only" in row:
                return True
            return False
        return "personal_local_only" in data or "local_only" in data


def _effective_from(data: dict[str, Any], user: str | None) -> dict[str, Any]:
    email = normalize_user(user)
    plo = _personal_local_only_from(data, email)
    row = _user_row(data, email)
    if "personal_local_only" in row:
        source = "user"
    elif "personal_local_only" in data and not _users_map(data):
        source = "runtime"
    else:
        source = "env"
    return {
        "personal_local_only": plo,
        "local_only": plo,  # chat escalate mirror for this account
        "autopilot_local_only": _autopilot_local_only_from(data),
        "user": email,
        "per_user": True,
        "source": source,
        "path": str(runtime_path()),
    }


def effective(user: str | None = None) -> dict[str, Any]:
    with _LOCK:
        return _effective_from(_load_unlocked(), user)


def set_personal_local_only(enabled: bool, *, user: str | None) -> dict[str, Any]:
    """Flip free-local-only mode for one signed-in account."""
    global _CACHE
    email = normalize_user(user)
    if not email:
        raise ValueError("user email required for per-account local-only")
    with _LOCK:
        data = _load_unlocked()
        users = _users_map(data)
        row = dict(users.get(email) or {}) if isinstance(users.get(email), dict) else {}
        row["personal_local_only"] = bool(enabled)
        users[email] = row
        data["users"] = users
        # Drop legacy global chat flag once per-user storage is in use so
        # other accounts are not stuck inheriting a shared toggle.
        data.pop("personal_local_only", None)
        path = runtime_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _CACHE = data
        return _effective_from(data, email)
