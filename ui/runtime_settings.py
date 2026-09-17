"""Persisted runtime settings for Hawkeye UI (survives process restart).

Stored under state/hawkeye-runtime.json so operators can flip switches in the UI
without editing .env. Env vars remain the default when no override is set.
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
    _CACHE = data
    return dict(data)


def load() -> dict[str, Any]:
    with _LOCK:
        return _load_unlocked()


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into runtime file and return effective settings."""
    global _CACHE
    with _LOCK:
        data = _load_unlocked()
        for key, val in updates.items():
            if val is None:
                data.pop(key, None)
            else:
                data[key] = val
        path = runtime_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _CACHE = data
        return _effective_from(data)


def clear_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None


def _personal_local_only_from(data: dict[str, Any]) -> bool:
    if "personal_local_only" in data:
        return bool(data["personal_local_only"])
    return _env_bool("AUTOCODE_PERSONAL_LOCAL_ONLY", "0")


def _autopilot_local_only_from(data: dict[str, Any]) -> bool:
    if "personal_local_only" in data and data["personal_local_only"]:
        return True
    if "local_only" in data:
        return bool(data["local_only"])
    if _personal_local_only_from(data):
        return True
    return _env_bool("AUTOCODE_LOCAL_ONLY", "0")


def personal_local_only() -> bool:
    """True when UI/chat must stay on the free local model (no Cursor/Grok)."""
    with _LOCK:
        return _personal_local_only_from(_load_unlocked())


def autopilot_local_only() -> bool:
    """True when overnight/worker routing should not require cloud delegates."""
    with _LOCK:
        return _autopilot_local_only_from(_load_unlocked())


def has_local_only_override() -> bool:
    with _LOCK:
        data = _load_unlocked()
        return "personal_local_only" in data or "local_only" in data


def _effective_from(data: dict[str, Any]) -> dict[str, Any]:
    plo = _personal_local_only_from(data)
    return {
        "personal_local_only": plo,
        "local_only": _autopilot_local_only_from(data),
        "source": "runtime" if ("personal_local_only" in data or "local_only" in data) else "env",
        "path": str(runtime_path()),
    }


def effective() -> dict[str, Any]:
    with _LOCK:
        return _effective_from(_load_unlocked())


def set_personal_local_only(enabled: bool) -> dict[str, Any]:
    """Flip free-local-only mode. Also mirrors local_only for readiness."""
    return save(
        {
            "personal_local_only": bool(enabled),
            "local_only": bool(enabled),
        }
    )
