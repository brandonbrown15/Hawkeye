#!/usr/bin/env python3
"""Hawkeye / private personal mode auth for the UI.

When AUTOCODE_PRIVATE_MODE=1 (default in the Hawkeye private repo):
  - username/password login required (session cookie)
  - local Ollama is the free all-day model
  - Cursor / Grok Bot (and optional API keys) still escalate hard asks
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from http.cookies import SimpleCookie
from typing import Any


SESSION_TTL_SEC = int(os.environ.get("AUTOCODE_PRIVATE_SESSION_HOURS", "720")) * 3600
COOKIE_NAME = "hawkeye_session"

# In-memory sessions: token -> {user, exp}
_SESSIONS: dict[str, dict[str, Any]] = {}


def product_name() -> str:
    return (os.environ.get("AUTOCODE_PRODUCT_NAME") or "Hawkeye").strip() or "Hawkeye"


def public_host() -> str:
    return (
        os.environ.get("AUTOCODE_PUBLIC_HOST") or "hawkeye.brownhawke.engineering"
    ).strip() or "hawkeye.brownhawke.engineering"


def private_mode_enabled() -> bool:
    return os.environ.get("AUTOCODE_PRIVATE_MODE", "0").lower() in ("1", "true", "yes", "on")


def personal_local_only() -> bool:
    """Opt-in: block all cloud escalate (rare). Default off — local-first with Cursor/Grok."""
    return os.environ.get("AUTOCODE_PERSONAL_LOCAL_ONLY", "0").lower() in ("1", "true", "yes", "on")


def _pbkdf2(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return dk.hex()


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    return f"pbkdf2_sha256$120000${salt}${_pbkdf2(password, salt)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$", 3)
    except ValueError:
        if os.environ.get("AUTOCODE_ALLOW_PLAINTEXT_PASSWORD", "0") == "1":
            return secrets.compare_digest(password, stored)
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        n = int(iters)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), n).hex()
    return hmac.compare_digest(dk, digest)


def configured_username() -> str:
    return os.environ.get("AUTOCODE_PRIVATE_USER", "brown").strip() or "brown"


def configured_password_hash() -> str:
    return os.environ.get("AUTOCODE_PRIVATE_PASSWORD_HASH", "").strip()


def credentials_ready() -> bool:
    return bool(configured_password_hash())


def login(username: str, password: str) -> str | None:
    """Return session token on success, else None."""
    if not private_mode_enabled():
        return secrets.token_urlsafe(24)
    if not credentials_ready():
        return None
    if not secrets.compare_digest(username.strip(), configured_username()):
        return None
    if not verify_password(password, configured_password_hash()):
        return None
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "user": username.strip(),
        "exp": time.time() + SESSION_TTL_SEC,
    }
    return token


def logout(token: str | None) -> None:
    if token:
        _SESSIONS.pop(token, None)


def clear_sessions() -> None:
    _SESSIONS.clear()


def session_valid(token: str | None) -> bool:
    if not private_mode_enabled():
        return True
    if not token:
        return False
    row = _SESSIONS.get(token)
    if not row:
        return False
    if time.time() > float(row.get("exp", 0)):
        _SESSIONS.pop(token, None)
        return False
    row["exp"] = time.time() + SESSION_TTL_SEC
    return True


def parse_session_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:  # noqa: BLE001
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


def session_cookie_header(token: str, secure: bool = False) -> str:
    parts = [
        f"{COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={SESSION_TTL_SEC}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie_header() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
