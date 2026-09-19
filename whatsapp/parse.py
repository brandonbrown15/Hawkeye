"""Parse WhatsApp Cloud API webhook JSON into inbound text events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    from_phone: str
    text: str
    message_id: str
    timestamp: str = ""
    message_type: str = "text"
    phone_number_id: str = ""
    contact_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_text(self) -> bool:
        return self.message_type == "text" and bool(self.text.strip())


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def parse_inbound(event: dict[str, Any] | None) -> list[InboundMessage]:
    """Extract user messages. Status/ack webhooks return []."""
    if not isinstance(event, dict):
        return []
    out: list[InboundMessage] = []
    for entry in _as_list(event.get("entry")):
        if not isinstance(entry, dict):
            continue
        for change in _as_list(entry.get("changes")):
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            names: dict[str, str] = {}
            for contact in _as_list(value.get("contacts")):
                if not isinstance(contact, dict):
                    continue
                wa_id = str(contact.get("wa_id") or "")
                profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
                names[wa_id] = str(profile.get("name") or "")
            for msg in _as_list(value.get("messages")):
                if not isinstance(msg, dict):
                    continue
                from_phone = str(msg.get("from") or "")
                mid = str(msg.get("id") or "")
                mtype = str(msg.get("type") or "unknown")
                text = ""
                if mtype == "text":
                    body = msg.get("text") if isinstance(msg.get("text"), dict) else {}
                    text = str(body.get("body") or "")
                elif mtype == "button":
                    button = msg.get("button") if isinstance(msg.get("button"), dict) else {}
                    text = str(button.get("text") or "")
                elif mtype == "interactive":
                    interactive = (
                        msg.get("interactive") if isinstance(msg.get("interactive"), dict) else {}
                    )
                    btn = interactive.get("button_reply")
                    lst = interactive.get("list_reply")
                    if isinstance(btn, dict):
                        text = str(btn.get("title") or btn.get("id") or "")
                    elif isinstance(lst, dict):
                        text = str(lst.get("title") or lst.get("id") or "")
                out.append(
                    InboundMessage(
                        from_phone=from_phone,
                        text=text.strip(),
                        message_id=mid,
                        timestamp=str(msg.get("timestamp") or ""),
                        message_type=mtype,
                        phone_number_id=phone_number_id,
                        contact_name=names.get(from_phone, ""),
                        raw=msg,
                    )
                )
    return out
