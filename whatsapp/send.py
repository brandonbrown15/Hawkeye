"""Outbound WhatsApp Cloud API text messages (stdlib HTTP)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from whatsapp import config

UrlOpener = Callable[..., Any]


def send_text(
    to: str,
    body: str,
    *,
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    """Send a session text message. Works inside Meta's 24h customer-care window."""
    dest = config.normalize_number(to)
    text = (body or "").strip()
    if not dest:
        return {"ok": False, "error": "missing destination number"}
    if not text:
        return {"ok": False, "error": "empty message"}
    if not config.number_allowed(dest):
        return {"ok": False, "error": "destination not on allowlist"}
    phone_id = config.secret("phone_number_id")
    token = config.secret("access_token")
    if not phone_id or not token:
        return {"ok": False, "error": "WhatsApp not configured"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": dest,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    return _post_graph(payload, phone_id=phone_id, token=token, opener=opener)


def send_template(
    to: str,
    *,
    template: str,
    body_text: str,
    language: str = "en_US",
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    """Optional approved template for business-initiated notifies outside 24h."""
    dest = config.normalize_number(to)
    name = (template or "").strip()
    if not dest or not name:
        return {"ok": False, "error": "template name and destination required"}
    if not config.number_allowed(dest):
        return {"ok": False, "error": "destination not on allowlist"}
    phone_id = config.secret("phone_number_id")
    token = config.secret("access_token")
    if not phone_id or not token:
        return {"ok": False, "error": "WhatsApp not configured"}
    payload = {
        "messaging_product": "whatsapp",
        "to": dest,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language or "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": (body_text or "")[:1024]}],
                }
            ],
        },
    }
    return _post_graph(payload, phone_id=phone_id, token=token, opener=opener)


def _post_graph(
    payload: dict[str, Any],
    *,
    phone_id: str,
    token: str,
    opener: UrlOpener | None,
) -> dict[str, Any]:
    req = urllib.request.Request(
        config.graph_messages_url(phone_id),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Hawkeye/1.0",
        },
        method="POST",
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace") if hasattr(resp, "read") else "{}"
            status = getattr(resp, "status", 200)
        data = json.loads(raw or "{}") if raw else {}
        if not isinstance(data, dict):
            data = {"raw": raw}
        mid = ""
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            mid = str(messages[0].get("id") or "")
        return {"ok": 200 <= int(status) < 300, "id": mid, "status": status, "response": data}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"graph {e.code}: {detail}", "status": e.code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
