"""Resend inbound webhook helpers (stdlib Svix-style verification)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


class WebhookError(ValueError):
    pass


def verify_svix_signature(
    payload: bytes | str,
    *,
    headers: dict[str, str],
    secret: str,
    tolerance_sec: int = 300,
) -> dict[str, Any]:
    """Verify Resend/Svix webhook signature and return parsed JSON.

    Secret may be `whsec_...` (base64) or a raw shared secret string.
    """
    if isinstance(payload, str):
        body = payload.encode("utf-8")
        payload_text = payload
    else:
        body = payload
        payload_text = payload.decode("utf-8")

    msg_id = _header(headers, "svix-id") or _header(headers, "webhook-id")
    timestamp = _header(headers, "svix-timestamp") or _header(headers, "webhook-timestamp")
    signature = _header(headers, "svix-signature") or _header(headers, "webhook-signature")
    if not msg_id or not timestamp or not signature:
        raise WebhookError("missing svix signature headers")

    try:
        ts = int(timestamp)
    except ValueError as e:
        raise WebhookError("bad timestamp") from e
    if abs(int(time.time()) - ts) > tolerance_sec:
        raise WebhookError("timestamp outside tolerance")

    key = _signing_key(secret)
    signed = f"{msg_id}.{timestamp}.".encode("utf-8") + body
    digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    accepted = False
    for part in signature.split(" "):
        part = part.strip()
        if not part:
            continue
        # Formats: v1,<b64> or bare b64
        if "," in part:
            ver, sig = part.split(",", 1)
            if ver not in ("v1", "v1a"):
                continue
        else:
            sig = part
        if hmac.compare_digest(sig, digest):
            accepted = True
            break
    if not accepted:
        raise WebhookError("invalid signature")

    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError as e:
        raise WebhookError("invalid json") from e
    if not isinstance(data, dict):
        raise WebhookError("payload must be object")
    return data


def _signing_key(secret: str) -> bytes:
    secret = (secret or "").strip()
    if secret.startswith("whsec_"):
        raw = secret[len("whsec_") :]
        try:
            return base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            return raw.encode("utf-8")
    return secret.encode("utf-8")


def _header(headers: dict[str, str], name: str) -> str:
    # Case-insensitive lookup
    want = name.lower()
    for key, val in headers.items():
        if key.lower() == want:
            return (val or "").strip()
    return ""


def extract_resend_envelope(event: dict[str, Any]) -> dict[str, str]:
    """Normalize Resend email.received payload into from/to/subject/email_id."""
    data = event.get("data") if isinstance(event.get("data"), dict) else event
    from_addr = ""
    to_addr = ""
    subject = str(data.get("subject") or "")
    email_id = str(data.get("email_id") or data.get("id") or "")

    raw_from = data.get("from")
    if isinstance(raw_from, str):
        from_addr = raw_from
    elif isinstance(raw_from, dict):
        from_addr = str(raw_from.get("email") or raw_from.get("address") or "")

    raw_to = data.get("to")
    if isinstance(raw_to, str):
        to_addr = raw_to
    elif isinstance(raw_to, list) and raw_to:
        first = raw_to[0]
        if isinstance(first, str):
            to_addr = first
        elif isinstance(first, dict):
            to_addr = str(first.get("email") or first.get("address") or "")

    return {
        "from": from_addr,
        "to": to_addr,
        "subject": subject,
        "email_id": email_id,
        "type": str(event.get("type") or data.get("type") or ""),
    }


def fetch_resend_email_body(email_id: str) -> str:
    """Pull received email content from Resend Receiving API (stdlib)."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        raise WebhookError("RESEND_API_KEY not set")
    if not email_id:
        raise WebhookError("missing email_id")
    import urllib.request

    req = urllib.request.Request(
        f"https://api.resend.com/emails/receiving/{email_id}",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "Hawkeye/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if not isinstance(payload, dict):
        return ""
    # SDK shape may nest under data
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    text = str(data.get("text") or "").strip()
    if text:
        return text
    html = str(data.get("html") or "").strip()
    if html:
        # crude strip
        import re

        return re.sub(r"<[^>]+>", " ", html)
    return str(data.get("body") or "")
