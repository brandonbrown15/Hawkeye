"""Operator WhatsApp notifications (queue empty, blocked, needs-human, digest)."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any

from whatsapp import config, send

_LOCK = threading.Lock()
_RECENT: dict[str, float] = {}


def rule_enabled(kind: str) -> bool:
    return config.notify_rule_enabled(kind)


def _dedup_sec() -> float:
    try:
        return float(os.environ.get("HAWKEYE_WHATSAPP_NOTIFY_DEDUP_SEC", "60") or 60)
    except ValueError:
        return 60.0


def _fingerprint(kind: str, text: str) -> str:
    raw = f"{kind}:{text[:120]}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def _should_send(kind: str, text: str, *, force: bool) -> bool:
    if force or kind == "test":
        return True
    if not rule_enabled(kind):
        return False
    window = _dedup_sec()
    if window <= 0:
        return True
    key = _fingerprint(kind, text)
    now = time.time()
    with _LOCK:
        stale = [k for k, ts in _RECENT.items() if now - ts > window]
        for k in stale:
            _RECENT.pop(k, None)
        last = _RECENT.get(key)
        if last is not None and now - last < window:
            return False
        _RECENT[key] = now
    return True


def notify_destinations() -> list[str]:
    explicit = config.parse_number_list(os.environ.get("HAWKEYE_WHATSAPP_NOTIFY_TO", ""))
    return explicit or config.allowed_numbers()


def notify_operator(
    kind: str,
    text: str,
    *,
    force: bool = False,
    opener=None,
) -> dict[str, Any]:
    """Send a WhatsApp alert to allowlisted numbers when the rule is on."""
    kind = (kind or "").strip().lower()
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "empty notify text", "sent": 0}
    if not config.enabled() and not force:
        return {"ok": False, "error": "whatsapp disabled or unconfigured", "sent": 0}
    if not _should_send(kind, body, force=force):
        return {"ok": True, "skipped": True, "reason": "rule or dedup", "sent": 0}

    dests = notify_destinations()
    if not dests:
        return {"ok": False, "error": "no allowlisted notify destinations", "sent": 0}

    template = os.environ.get("HAWKEYE_WHATSAPP_NOTIFY_TEMPLATE", "").strip()
    language = os.environ.get("HAWKEYE_WHATSAPP_NOTIFY_TEMPLATE_LANG", "en_US").strip() or "en_US"
    results: list[dict[str, Any]] = []
    sent = 0
    for dest in dests:
        if template:
            out = send.send_template(
                dest,
                template=template,
                body_text=body,
                language=language,
                opener=opener,
            )
            if not out.get("ok"):
                # Fall back to session text when the template is unused / window is open.
                out = send.send_text(dest, body, opener=opener)
        else:
            out = send.send_text(dest, body, opener=opener)
        results.append({"to": dest, **out})
        if out.get("ok"):
            sent += 1
    return {"ok": sent > 0, "sent": sent, "kind": kind, "results": results}


def wrap_sink(sink: Any) -> Any:
    """Wrap a Notion sink so Blocked / Human escalate fire WhatsApp."""

    class _NotifyingSink:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def blocked(self, page_id: str) -> None:
            self._inner.blocked(page_id)
            notify_operator(
                "blocked",
                f"Hawkeye: a task is Blocked and needs you.\npage={page_id}",
            )

        def escalate(
            self,
            name: str,
            why: str,
            context: str,
            send_to: str = "Human",
            pr: str | None = None,
        ) -> None:
            self._inner.escalate(name, why, context, send_to=send_to, pr=pr)
            if str(send_to or "").strip().lower() == "human":
                extra = f"\nPR: {pr}" if pr else ""
                notify_operator(
                    "human",
                    f"Hawkeye needs a human decision.\n"
                    f"Task: {name}\nWhy: {why}\n{(context or '')[:400]}{extra}",
                )

    return _NotifyingSink(sink)
