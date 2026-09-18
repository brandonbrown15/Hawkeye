#!/usr/bin/env python3
"""Hawkeye work-platform auth for the UI.

When AUTOCODE_PRIVATE_MODE=1 (default in the Hawkeye private repo):
  - email + password login required (session cookie)
  - only addresses on HAWKEYE_ALLOWED_EMAIL_DOMAIN (default brownhawke.engineering)
  - local Ollama is the free all-day model
  - Cursor / Grok Bot (and optional API keys) still escalate hard asks
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


SESSION_TTL_SEC = int(os.environ.get("AUTOCODE_PRIVATE_SESSION_HOURS", "720")) * 3600
COOKIE_NAME = "hawkeye_session"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USERS_FILE = ROOT / "config" / "users.json"

# In-memory sessions: token -> {user, exp}
_SESSIONS: dict[str, dict[str, Any]] = {}
_USERS_CACHE: dict[str, str] | None = None


def product_name() -> str:
    return (os.environ.get("AUTOCODE_PRODUCT_NAME") or "Hawkeye").strip() or "Hawkeye"


def public_host() -> str:
    return (
        os.environ.get("AUTOCODE_PUBLIC_HOST") or "hawkeye.brownhawke.engineering"
    ).strip() or "hawkeye.brownhawke.engineering"


def allowed_email_domain() -> str:
    return (
        os.environ.get("HAWKEYE_ALLOWED_EMAIL_DOMAIN") or "brownhawke.engineering"
    ).strip().lower().lstrip("@") or "brownhawke.engineering"


def private_mode_enabled() -> bool:
    return os.environ.get("AUTOCODE_PRIVATE_MODE", "0").lower() in ("1", "true", "yes", "on")


def personal_local_only(user: str | None = None) -> bool:
    """Opt-in: block cloud escalate for this signed-in account.

    Default off — local-first with Cursor/Grok escalate for hard asks.
    Each @brownhawke.engineering user has their own UI toggle.
    """
    from ui import runtime_settings

    return runtime_settings.personal_local_only(user)


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


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_allowed_email(email: str) -> bool:
    email = normalize_email(email)
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    return domain == allowed_email_domain()


def users_file_path() -> Path:
    raw = os.environ.get("HAWKEYE_USERS_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_USERS_FILE


def _load_users_uncached() -> dict[str, str]:
    """Map normalized email → password hash."""
    users: dict[str, str] = {}

    path = users_file_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            raw_users = data.get("users", data)
            if isinstance(raw_users, dict):
                for email, digest in raw_users.items():
                    if isinstance(email, str) and isinstance(digest, str) and digest.strip():
                        users[normalize_email(email)] = digest.strip()

    # Optional env JSON: {"brandon@brownhawke.engineering":"pbkdf2_..."}
    raw_json = os.environ.get("HAWKEYE_USERS_JSON", "").strip()
    if raw_json:
        try:
            extra = json.loads(raw_json)
        except json.JSONDecodeError:
            extra = {}
        if isinstance(extra, dict):
            for email, digest in extra.items():
                if isinstance(email, str) and isinstance(digest, str) and digest.strip():
                    users[normalize_email(email)] = digest.strip()

    # Legacy single-user env (username may be bare local-part or full email).
    legacy_user = os.environ.get("AUTOCODE_PRIVATE_USER", "").strip()
    legacy_hash = os.environ.get("AUTOCODE_PRIVATE_PASSWORD_HASH", "").strip()
    if legacy_user and legacy_hash:
        email = normalize_email(legacy_user)
        if "@" not in email:
            email = f"{email}@{allowed_email_domain()}"
        users.setdefault(email, legacy_hash)

    return users


def load_users(*, reload: bool = False) -> dict[str, str]:
    global _USERS_CACHE
    if _USERS_CACHE is None or reload:
        _USERS_CACHE = _load_users_uncached()
    return dict(_USERS_CACHE)


def clear_users_cache() -> None:
    global _USERS_CACHE
    _USERS_CACHE = None


def configured_username() -> str:
    """Backward-compatible hint for docs / readiness."""
    users = load_users()
    if users:
        return sorted(users.keys())[0]
    legacy = os.environ.get("AUTOCODE_PRIVATE_USER", "").strip()
    if legacy:
        return legacy
    return f"you@{allowed_email_domain()}"


def configured_password_hash() -> str:
    users = load_users()
    if users:
        return next(iter(users.values()))
    return os.environ.get("AUTOCODE_PRIVATE_PASSWORD_HASH", "").strip()


def credentials_ready() -> bool:
    return bool(load_users())


def login(username: str, password: str) -> str | None:
    """Return session token on success, else None.

    `username` is treated as a work email (case-insensitive).
    """
    if not private_mode_enabled():
        return secrets.token_urlsafe(24)
    if not credentials_ready():
        return None

    email = normalize_email(username)
    # Allow typing only the local part on the login form.
    if email and "@" not in email:
        email = f"{email}@{allowed_email_domain()}"

    if not is_allowed_email(email):
        return None

    users = load_users()
    stored = users.get(email)
    if not stored:
        return None
    if not verify_password(password, stored):
        return None

    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "user": email,
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


def session_user(token: str | None) -> str | None:
    if not token or not session_valid(token):
        return None
    row = _SESSIONS.get(token) or {}
    user = row.get("user")
    return str(user) if user else None


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
