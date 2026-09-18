"""Persisted inbound mail under the Hawkeye data root."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()


def mail_dir() -> Path:
    raw = os.environ.get("HAWKEYE_MAIL_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        data = Path(os.environ.get("AUTOCODE_DATA_ROOT", "")).expanduser()
        if data and str(data):
            path = data / "hawkeye" / "mail"
        else:
            path = ROOT / "state" / "mail"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return mail_dir() / "inbox.jsonl"


@dataclass
class MailMessage:
    id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    received_at: float
    status: str = "new"  # new | drafted | sent | ignored | rejected
    draft: str = ""
    reply_id: str = ""
    provider: str = "resend"
    external_id: str = ""
    reject_reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MailMessage":
        return cls(
            id=str(data.get("id") or ""),
            from_addr=str(data.get("from_addr") or data.get("from") or ""),
            to_addr=str(data.get("to_addr") or data.get("to") or ""),
            subject=str(data.get("subject") or ""),
            body=str(data.get("body") or ""),
            received_at=float(data.get("received_at") or time.time()),
            status=str(data.get("status") or "new"),
            draft=str(data.get("draft") or ""),
            reply_id=str(data.get("reply_id") or ""),
            provider=str(data.get("provider") or "resend"),
            external_id=str(data.get("external_id") or ""),
            reject_reason=str(data.get("reject_reason") or ""),
            meta=dict(data.get("meta") or {}) if isinstance(data.get("meta"), dict) else {},
        )


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def append_message(msg: MailMessage) -> MailMessage:
    with _LOCK:
        path = _index_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
    return msg


def list_messages(*, limit: int = 50, status: str | None = None) -> list[MailMessage]:
    rows = _load_all()
    if status and status != "all":
        rows = [m for m in rows if m.status == status]
    rows.sort(key=lambda m: m.received_at, reverse=True)
    return rows[: max(1, min(limit, 200))]


def get_message(msg_id: str) -> MailMessage | None:
    for msg in _load_all():
        if msg.id == msg_id:
            return msg
    return None


def update_message(msg_id: str, **updates: Any) -> MailMessage | None:
    with _LOCK:
        rows = _load_all_unlocked()
        found: MailMessage | None = None
        out: list[MailMessage] = []
        for msg in rows:
            if msg.id == msg_id:
                data = msg.to_dict()
                data.update(updates)
                msg = MailMessage.from_dict(data)
                found = msg
            out.append(msg)
        if found is None:
            return None
        _rewrite(out)
        return found


def stats() -> dict[str, Any]:
    rows = _load_all()
    counts: dict[str, int] = {}
    for msg in rows:
        counts[msg.status] = counts.get(msg.status, 0) + 1
    return {
        "total": len(rows),
        "by_status": counts,
        "path": str(_index_path()),
        "enabled": os.environ.get("HAWKEYE_MAIL_ENABLED", "0").lower()
        in ("1", "true", "yes", "on"),
    }


def _load_all() -> list[MailMessage]:
    with _LOCK:
        return _load_all_unlocked()


def _load_all_unlocked() -> list[MailMessage]:
    path = _index_path()
    if not path.is_file():
        return []
    rows: list[MailMessage] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(MailMessage.from_dict(data))
    except OSError:
        return []
    return rows


def _rewrite(rows: list[MailMessage]) -> None:
    path = _index_path()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for msg in rows:
            fh.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
    tmp.replace(path)
