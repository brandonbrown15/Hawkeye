"""Hawkeye inbound email inbox (Resend webhook + local draft/reply).

Security defaults (strict):
  - Domain allowlist: HAWKEYE_ALLOWED_EMAIL_DOMAIN (brownhawke.engineering)
  - Optional exact sender allowlist: HAWKEYE_MAIL_ALLOWED_SENDERS
  - Human approve-before-send (HAWKEYE_MAIL_AUTO_SEND=0)
  - Webhook signature required when RESEND_WEBHOOK_SECRET is set
"""

from __future__ import annotations

from mail.service import (
    draft_reply,
    handle_inbound_payload,
    ignore_message,
    list_messages,
    send_reply,
    stats,
)
from mail.store import MailMessage, get_message

__all__ = [
    "MailMessage",
    "draft_reply",
    "get_message",
    "handle_inbound_payload",
    "ignore_message",
    "list_messages",
    "send_reply",
    "stats",
]
