"""Inbound mail processing: accept → draft → optional send."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from mail import security, store, webhook
from mail.store import MailMessage


def enabled() -> bool:
    return os.environ.get("HAWKEYE_MAIL_ENABLED", "0").lower() in ("1", "true", "yes", "on")


def stats() -> dict[str, Any]:
    return store.stats()


def list_messages(*, limit: int = 50, status: str | None = None) -> dict[str, Any]:
    rows = store.list_messages(limit=limit, status=status)
    return {
        "ok": True,
        "enabled": enabled(),
        "messages": [m.to_dict() for m in rows],
        **store.stats(),
    }


def handle_inbound_payload(
    payload: bytes | str,
    *,
    headers: dict[str, str] | None = None,
    body_override: str | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Process a Resend webhook (or a manually posted envelope)."""
    headers = headers or {}
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "").strip()

    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raw = str(payload).encode("utf-8")

    if secret and not skip_verify:
        event = webhook.verify_svix_signature(raw, headers=headers, secret=secret)
    else:
        if secret and not skip_verify:
            return {"ok": False, "error": "webhook secret configured but verify skipped"}
        try:
            event = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid json"}
        if not isinstance(event, dict):
            return {"ok": False, "error": "payload must be object"}

    # Support manual inject: {from,to,subject,body}
    if body_override is None and event.get("body") and not event.get("type"):
        return _ingest_manual(event)

    envelope = webhook.extract_resend_envelope(event)
    event_type = envelope.get("type") or ""
    if event_type and event_type != "email.received":
        return {"ok": True, "ignored": True, "reason": f"event {event_type}"}

    from_addr = envelope["from"]
    to_addr = envelope["to"]
    subject = envelope["subject"]
    email_id = envelope["email_id"]

    allowed, reason = security.sender_allowed(from_addr)
    if not allowed:
        msg = MailMessage(
            id=store.new_id(),
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body="",
            received_at=time.time(),
            status="rejected",
            reject_reason=reason,
            external_id=email_id,
            meta=security.audit_event("rejected", reason=reason),
        )
        store.append_message(msg)
        return {"ok": True, "rejected": True, "reason": reason, "id": msg.id}

    body = body_override or ""
    if not body and email_id and os.environ.get("RESEND_API_KEY", "").strip():
        try:
            body = webhook.fetch_resend_email_body(email_id)
        except Exception as e:  # noqa: BLE001
            body = f"(failed to fetch email body: {e})"

    suspicious = security.content_suspicious(f"{subject}\n{body}")
    if suspicious:
        msg = MailMessage(
            id=store.new_id(),
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body=security.strip_quoted_content(body),
            received_at=time.time(),
            status="rejected",
            reject_reason=suspicious,
            external_id=email_id,
            meta=security.audit_event("content_blocked", reason=suspicious),
        )
        store.append_message(msg)
        return {"ok": True, "rejected": True, "reason": suspicious, "id": msg.id}

    msg = MailMessage(
        id=store.new_id(),
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body=security.strip_quoted_content(body),
        received_at=time.time(),
        status="new",
        external_id=email_id,
        provider="resend",
    )
    store.append_message(msg)

    auto_draft = os.environ.get("HAWKEYE_MAIL_AUTO_DRAFT", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    draft_out: dict[str, Any] | None = None
    if auto_draft:
        draft_out = draft_reply(msg.id)

    auto_send = os.environ.get("HAWKEYE_MAIL_AUTO_SEND", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    send_out: dict[str, Any] | None = None
    if auto_send and draft_out and draft_out.get("ok"):
        send_out = send_reply(msg.id)

    return {
        "ok": True,
        "id": msg.id,
        "status": store.get_message(msg.id).status if store.get_message(msg.id) else msg.status,
        "draft": draft_out,
        "sent": send_out,
    }


def _ingest_manual(event: dict[str, Any]) -> dict[str, Any]:
    """Dev/helper path: POST {from,to,subject,body} without Resend."""
    from_addr = str(event.get("from") or event.get("from_addr") or "")
    to_addr = str(event.get("to") or event.get("to_addr") or "")
    subject = str(event.get("subject") or "")
    body = str(event.get("body") or "")
    synthetic = {
        "type": "email.received",
        "data": {
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "email_id": "",
        },
    }
    return handle_inbound_payload(
        json.dumps(synthetic),
        headers={},
        body_override=body,
        skip_verify=True,
    )


def draft_reply(msg_id: str) -> dict[str, Any]:
    msg = store.get_message(msg_id)
    if not msg:
        return {"ok": False, "error": "message not found"}
    if msg.status == "rejected":
        return {"ok": False, "error": "message was rejected"}

    product = (os.environ.get("AUTOCODE_PRODUCT_NAME") or "Hawkeye").strip() or "Hawkeye"
    fenced = security.sanitize_for_prompt(msg.subject, msg.body)
    system = (
        f"You are {product}, BrownHawke Engineering's private assistant. "
        "Draft a short, professional email reply. "
        "Do not invent commitments, credentials, or wire instructions. "
        "If the email needs a human decision, say so and propose next steps. "
        "Output only the reply body (no Subject: line)."
    )
    # Optional deep research when the mail itself asks for lookup.
    research_note = ""
    try:
        from research import research as do_research, wants_research

        if wants_research(f"{msg.subject}\n{msg.body}"):
            result = do_research(f"{msg.subject} {msg.body[:200]}", limit=3)
            research_note = "\n\n" + result.format_for_prompt(limit=3)
    except Exception as e:  # noqa: BLE001
        research_note = f"\n\n(research skipped: {e})"

    user = f"Reply to this inbound email.\n\n{fenced}{research_note}"
    try:
        draft = _ollama_chat(user, system)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"local model unavailable: {e}"}

    store.update_message(msg_id, draft=draft.strip(), status="drafted")
    return {"ok": True, "id": msg_id, "draft": draft.strip(), "status": "drafted"}


def send_reply(msg_id: str, *, draft: str | None = None) -> dict[str, Any]:
    msg = store.get_message(msg_id)
    if not msg:
        return {"ok": False, "error": "message not found"}
    body = (draft if draft is not None else msg.draft or "").strip()
    if not body:
        return {"ok": False, "error": "no draft to send — run draft first"}

    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "RESEND_API_KEY not set"}

    from_addr = (
        os.environ.get("HAWKEYE_MAIL_FROM", "").strip()
        or msg.to_addr
        or f"hawkeye@{(os.environ.get('HAWKEYE_ALLOWED_EMAIL_DOMAIN') or 'brownhawke.engineering')}"
    )
    subject = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject}"
    payload = {
        "from": from_addr,
        "to": [security.normalize_email(msg.from_addr)],
        "subject": subject,
        "text": body,
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Hawkeye/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"resend {e.code}: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

    reply_id = ""
    if isinstance(data, dict):
        reply_id = str(data.get("id") or (data.get("data") or {}).get("id") or "")
    store.update_message(msg_id, draft=body, status="sent", reply_id=reply_id)
    return {"ok": True, "id": msg_id, "reply_id": reply_id, "status": "sent"}


def ignore_message(msg_id: str) -> dict[str, Any]:
    msg = store.update_message(msg_id, status="ignored")
    if not msg:
        return {"ok": False, "error": "message not found"}
    return {"ok": True, "id": msg_id, "status": "ignored"}


def _ollama_chat(user: str, system: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("HAWKEYE_CHAT_MODEL") or os.environ.get(
        "AUTOCODE_LOCAL_MODEL", "coder-64k"
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict) and msg.get("content"):
        return str(msg["content"])
    return str(data)
