"""Inbound WhatsApp → same handle_chat / escalate path as the UI."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from whatsapp import config, history, parse, send
from whatsapp.webhook import WebhookError, verify_signature


def _skip_verify() -> bool:
    return os.environ.get("HAWKEYE_WHATSAPP_REQUIRE_SIGNATURE", "1").lower() in (
        "0",
        "false",
        "no",
        "off",
    )


def handle_inbound_payload(
    payload: bytes | str,
    *,
    headers: dict[str, str] | None = None,
    skip_verify: bool = False,
    background: bool = True,
) -> dict[str, Any]:
    """Verify, parse, allowlist, then chat + reply.

    Returns quickly. Chat/escalate runs in a background thread by default so
    Meta does not retry the webhook while Ollama/Cursor is still working.
    """
    headers = headers or {}
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raw = str(payload).encode("utf-8")

    if not skip_verify and not _skip_verify():
        verify_signature(raw, headers=headers)
    try:
        event = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise WebhookError("invalid json") from e
    if not isinstance(event, dict):
        raise WebhookError("payload must be object")

    messages = parse.parse_inbound(event)
    if not messages:
        return {"ok": True, "ignored": True, "reason": "no inbound messages"}

    accepted: list[dict[str, Any]] = []
    for msg in messages:
        if msg.message_id and history.already_seen(msg.message_id):
            accepted.append({"id": msg.message_id, "duplicate": True})
            continue
        if msg.message_id:
            history.mark_seen(msg.message_id)
        if not config.number_allowed(msg.from_phone):
            print(f"[whatsapp] rejected unauthorized sender {config.normalize_number(msg.from_phone)}")
            accepted.append(
                {
                    "id": msg.message_id,
                    "rejected": True,
                    "reason": "number not allowlisted",
                }
            )
            continue
        if background:
            threading.Thread(
                target=_process_message,
                args=(msg,),
                name=f"whatsapp-{msg.message_id or 'msg'}",
                daemon=True,
            ).start()
            accepted.append({"id": msg.message_id, "queued": True, "from": msg.from_phone})
        else:
            accepted.append(_process_message(msg))
    return {"ok": True, "accepted": accepted}


def _process_message(msg: parse.InboundMessage) -> dict[str, Any]:
    if not msg.is_text:
        reply = (
            "Hawkeye only reads text on WhatsApp for now. "
            "Send a written message and I will take the same path as the UI chat."
        )
        sent = send.send_text(msg.from_phone, reply)
        return {
            "ok": True,
            "id": msg.message_id,
            "unsupported": msg.message_type,
            "sent": sent,
        }

    prior = history.load_history(msg.from_phone)
    email = config.owner_email()
    try:
        from ui.server import handle_chat

        out = handle_chat(
            msg.text,
            seed_notion=True,
            email=email,
            history=prior,
        )
    except Exception as e:  # noqa: BLE001
        err = f"Hawkeye chat failed: {e}"
        send.send_text(msg.from_phone, err)
        return {"ok": False, "id": msg.message_id, "error": str(e)}

    reply = _reply_from_chat(out)
    history.append_turn(msg.from_phone, msg.text, reply)
    sent = send.send_text(msg.from_phone, reply)
    return {
        "ok": bool(out.get("ok")),
        "id": msg.message_id,
        "escalated": bool(out.get("escalated")),
        "provider": out.get("provider") or "",
        "reply": reply,
        "sent": sent,
        "seeded_task": out.get("seeded_task"),
    }


def _reply_from_chat(out: dict[str, Any]) -> str:
    if not isinstance(out, dict):
        return "Hawkeye could not answer just now."
    if out.get("escalated"):
        cloud = str(out.get("cloud_reply") or "").strip()
        if cloud:
            return cloud
        err = str(out.get("cloud_error") or "").strip()
        local = str(out.get("local_reply") or "").strip()
        bits = [p for p in (local, err) if p]
        return "\n\n".join(bits) or "Cloud escalate failed."
    local = str(out.get("local_reply") or "").strip()
    if local:
        return local
    err = str(out.get("local_error") or out.get("error") or "").strip()
    return err or "Hawkeye had no reply."
