"""Per-number chat history + inbound message-id dedup (local JSON)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from whatsapp import config

_LOCK = threading.RLock()
_MAX_TURNS = 16
_MAX_SEEN = 400


def _history_path():
    return config.data_dir() / "history.json"


def _seen_path():
    return config.data_dir() / "seen.json"


def _load(path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def already_seen(message_id: str) -> bool:
    mid = (message_id or "").strip()
    if not mid:
        return False
    with _LOCK:
        data = _load(_seen_path())
        ids = data.get("ids")
        if not isinstance(ids, list):
            ids = []
        return mid in ids


def mark_seen(message_id: str) -> None:
    mid = (message_id or "").strip()
    if not mid:
        return
    with _LOCK:
        path = _seen_path()
        data = _load(path)
        ids = [x for x in (data.get("ids") or []) if isinstance(x, str)]
        if mid in ids:
            return
        ids.append(mid)
        data["ids"] = ids[-_MAX_SEEN:]
        data["updated_at"] = time.time()
        _save(path, data)


def load_history(phone: str) -> list[dict[str, str]]:
    key = config.normalize_number(phone)
    if not key:
        return []
    with _LOCK:
        data = _load(_history_path())
        threads = data.get("threads") if isinstance(data.get("threads"), dict) else {}
        rows = threads.get(key) or []
    out: list[dict[str, str]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "")
            content = str(row.get("content") or "")
            if role in ("user", "assistant") and content:
                out.append({"role": role, "content": content})
    return out[-_MAX_TURNS:]


def append_turn(phone: str, user: str, assistant: str) -> None:
    key = config.normalize_number(phone)
    if not key:
        return
    with _LOCK:
        path = _history_path()
        data = _load(path)
        threads = dict(data.get("threads") or {}) if isinstance(data.get("threads"), dict) else {}
        rows = list(threads.get(key) or [])
        if user:
            rows.append({"role": "user", "content": user, "ts": time.time()})
        if assistant:
            rows.append({"role": "assistant", "content": assistant, "ts": time.time()})
        threads[key] = rows[-(_MAX_TURNS * 2) :]
        data["threads"] = threads
        data["updated_at"] = time.time()
        _save(path, data)
