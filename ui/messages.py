"""Direct messages between Hawkeye coworkers (same work domain)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ui import accounts
from ui import auth as ui_auth

_LOCK = threading.RLock()


def messages_path() -> Path:
    return accounts.accounts_root() / "messages.jsonl"


def thread_id_for(a: str, b: str) -> str:
    x = ui_auth.normalize_email(a)
    y = ui_auth.normalize_email(b)
    lo, hi = sorted([x, y])
    return f"dm:{lo}:{hi}"


def _append(msg: dict[str, Any]) -> None:
    path = messages_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(msg, ensure_ascii=False) + "\n")


def _load_all() -> list[dict[str, Any]]:
    path = messages_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except OSError:
        return []
    return rows


def _rewrite(rows: list[dict[str, Any]]) -> None:
    path = messages_path()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def send_message(from_email: str, to_email: str, body: str) -> dict[str, Any]:
    from_email = ui_auth.normalize_email(from_email)
    to_email = ui_auth.normalize_email(to_email)
    body = (body or "").strip()
    if not body:
        raise ValueError("message body required")
    if from_email == to_email:
        raise ValueError("cannot DM yourself")
    if not ui_auth.is_allowed_email(to_email):
        raise ValueError("recipient must be on the allowed work domain")
    if to_email not in ui_auth.load_users():
        raise ValueError("recipient has no Hawkeye login")
    msg = {
        "id": "msg_" + uuid.uuid4().hex[:12],
        "thread_id": thread_id_for(from_email, to_email),
        "from": from_email,
        "to": to_email,
        "body": body[:8000],
        "ts": time.time(),
        "read_at": None,
    }
    with _LOCK:
        _append(msg)
    return {"ok": True, "message": msg}


def list_threads(email: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        rows = _load_all()
    latest: dict[str, dict[str, Any]] = {}
    unread: dict[str, int] = {}
    for msg in rows:
        if email not in (msg.get("from"), msg.get("to")):
            continue
        tid = str(msg.get("thread_id") or "")
        if not tid:
            continue
        prev = latest.get(tid)
        if not prev or float(msg.get("ts") or 0) >= float(prev.get("ts") or 0):
            latest[tid] = msg
        if msg.get("to") == email and not msg.get("read_at"):
            unread[tid] = unread.get(tid, 0) + 1
    threads = []
    for tid, msg in latest.items():
        other = msg["to"] if msg.get("from") == email else msg.get("from")
        other = ui_auth.normalize_email(str(other or ""))
        profile = accounts.get_profile(other) if other else {}
        threads.append(
            {
                "thread_id": tid,
                "with": other,
                "with_name": profile.get("display_name") or other,
                "last_message": msg.get("body"),
                "last_ts": msg.get("ts"),
                "unread": unread.get(tid, 0),
            }
        )
    threads.sort(key=lambda t: float(t.get("last_ts") or 0), reverse=True)
    return {
        "ok": True,
        "threads": threads,
        "unread_total": sum(unread.values()),
    }


def get_thread(email: str, thread_id: str, *, limit: int = 100) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    thread_id = (thread_id or "").strip()
    with _LOCK:
        rows = [
            m
            for m in _load_all()
            if m.get("thread_id") == thread_id and email in (m.get("from"), m.get("to"))
        ]
    rows.sort(key=lambda m: float(m.get("ts") or 0))
    if limit > 0:
        rows = rows[-limit:]
    other = ""
    if rows:
        other = rows[0]["to"] if rows[0].get("from") == email else rows[0].get("from")
    return {
        "ok": True,
        "thread_id": thread_id,
        "with": ui_auth.normalize_email(str(other or "")),
        "messages": rows,
    }


def mark_thread_read(email: str, thread_id: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    thread_id = (thread_id or "").strip()
    now = time.time()
    changed = 0
    with _LOCK:
        rows = _load_all()
        for msg in rows:
            if msg.get("thread_id") != thread_id:
                continue
            if msg.get("to") == email and not msg.get("read_at"):
                msg["read_at"] = now
                changed += 1
        if changed:
            _rewrite(rows)
    return {"ok": True, "marked": changed}
