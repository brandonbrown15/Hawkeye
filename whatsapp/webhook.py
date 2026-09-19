"""Meta WhatsApp Cloud API webhook verify (GET) + HMAC-SHA256 (POST)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any


class WebhookError(ValueError):
    pass


def _first(qs: dict[str, Any], *names: str) -> str:
    for name in names:
        raw = qs.get(name)
        if isinstance(raw, list) and raw:
            return str(raw[0] or "").strip()
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _header(headers: dict[str, str], name: str) -> str:
    want = name.lower()
    for key, val in headers.items():
        if key.lower() == want:
            return (val or "").strip()
    return ""


def _tokens_match(got: str, expected: str) -> bool:
    if not expected:
        return False
    left = got.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def expected_verify_token() -> str:
    from whatsapp import config

    return config.secret("verify_token")


def expected_app_secret() -> str:
    from whatsapp import config

    return config.secret("app_secret")


def verify_subscription(
    qs: dict[str, Any],
    *,
    verify_token: str | None = None,
) -> str:
    """Return the hub.challenge when mode=subscribe and the token matches.

    Raises WebhookError on mismatch / missing config.
    """
    mode = _first(qs, "hub.mode", "hub_mode")
    token = _first(qs, "hub.verify_token", "hub_verify_token")
    challenge = _first(qs, "hub.challenge", "hub_challenge")
    expected = (verify_token if verify_token is not None else expected_verify_token()).strip()
    if mode != "subscribe":
        raise WebhookError("not a subscribe challenge")
    if not expected:
        raise WebhookError("verify token not configured")
    if not _tokens_match(token, expected):
        raise WebhookError("verify token mismatch")
    if not challenge:
        raise WebhookError("missing hub.challenge")
    return challenge


def handle_verify_request(
    qs: dict[str, Any],
    *,
    verify_token: str | None = None,
) -> tuple[int, bytes, str]:
    """HTTP triple for Meta's GET webhook handshake."""
    try:
        challenge = verify_subscription(qs, verify_token=verify_token)
    except WebhookError:
        return 403, b"forbidden", "text/plain; charset=utf-8"
    return 200, challenge.encode("utf-8"), "text/plain; charset=utf-8"


def signature_hex(payload: bytes | str, app_secret: str) -> str:
    if isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload
    return hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(
    payload: bytes | str,
    *,
    headers: dict[str, str],
    app_secret: str | None = None,
) -> None:
    """Validate X-Hub-Signature-256 (sha256=<hex>)."""
    secret = (app_secret if app_secret is not None else expected_app_secret()).strip()
    if not secret:
        raise WebhookError("app secret not configured")
    raw = _header(headers, "X-Hub-Signature-256") or _header(headers, "X-Hub-Signature")
    if not raw:
        raise WebhookError("missing X-Hub-Signature-256")
    got = raw.split("=", 1)[1].strip() if raw.lower().startswith("sha256=") else raw
    expect = signature_hex(payload, secret)
    if not hmac.compare_digest(got, expect):
        raise WebhookError("invalid signature")
