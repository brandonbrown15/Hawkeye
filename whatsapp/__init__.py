"""WhatsApp Cloud API (Meta) — inbound chat + operator notifications.

Official Graph API only. No WhatsApp Web scrapers / unofficial clients.
Secrets live in Account → Connections or machine .env — never in git.
"""

from __future__ import annotations

from whatsapp.notify import notify_operator, rule_enabled
from whatsapp.parse import InboundMessage, parse_inbound
from whatsapp.service import handle_inbound_payload
from whatsapp.webhook import (
    WebhookError,
    handle_verify_request,
    verify_signature,
    verify_subscription,
)

__all__ = [
    "InboundMessage",
    "WebhookError",
    "handle_inbound_payload",
    "handle_verify_request",
    "notify_operator",
    "parse_inbound",
    "rule_enabled",
    "verify_signature",
    "verify_subscription",
]
