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
from dataclasses import dataclass
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
_USERS_MTIME: float | None = None


# Structured login failures so the UI can tell users what actually happened
# (wrong password vs no account vs Cloudflare Access) instead of a silent bounce.
CODE_EMPTY = "empty"
CODE_NOT_CONFIGURED = "not_configured"
CODE_BAD_DOMAIN = "bad_domain"
CODE_UNKNOWN_ACCOUNT = "unknown_account"
CODE_WRONG_PASSWORD = "wrong_password"
CODE_COOKIE = "cookie_not_stored"
CODE_ACCESS = "access_blocked"


@dataclass(frozen=True)
class LoginFailure:
    code: str
    error: str
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"code": self.code, "error": self.error}
        if self.hint:
            out["hint"] = self.hint
        return out


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


def canonicalize_email(value: str) -> str:
    """Trim, lowercase, and append the work domain when only the local part is typed."""
    email = normalize_email(value)
    if email and "@" not in email:
        email = f"{email}@{allowed_email_domain()}"
    return email


def is_allowed_email(email: str) -> bool:
    email = canonicalize_email(email)
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


def _users_file_mtime() -> float | None:
    path = users_file_path()
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def load_users(*, reload: bool = False) -> dict[str, str]:
    """Map email → hash, refreshing when config/users.json changes on disk.

    The UI process used to cache forever, so `set_work_user.py` / password
    resets looked like a wrong password until hawkeye-ui was restarted.
    """
    global _USERS_CACHE, _USERS_MTIME
    mtime = _users_file_mtime()
    if _USERS_CACHE is None or reload or mtime != _USERS_MTIME:
        _USERS_CACHE = _load_users_uncached()
        _USERS_MTIME = mtime
    return dict(_USERS_CACHE)


def clear_users_cache() -> None:
    global _USERS_CACHE, _USERS_MTIME
    _USERS_CACHE = None
    _USERS_MTIME = None


def list_login_emails() -> list[str]:
    """Sorted work emails that can sign in (no hashes)."""
    return sorted(load_users().keys())


def upsert_user_password(email: str, password: str, *, users_file: Path | None = None) -> dict[str, Any]:
    """Create or update a work-email login. Writes the hash only (never the password)."""
    email = canonicalize_email(email)
    if not is_allowed_email(email):
        raise ValueError(
            f"Email must end with @{allowed_email_domain()} (got {email!r})"
        )
    if len(password) < 8:
        raise ValueError("Use at least 8 characters")
    path = Path(users_file).expanduser() if users_file else users_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"allowed_domain": allowed_email_domain(), "users": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
                data.setdefault("users", {})
        except json.JSONDecodeError:
            pass
    users = data.setdefault("users", {})
    created = email not in users
    users[email] = hash_password(password)
    data["allowed_domain"] = allowed_email_domain()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    clear_users_cache()
    return {
        "email": email,
        "path": str(path),
        "created": created,
        "users": list_login_emails(),
    }


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


def _reset_hint(email: str | None = None) -> str:
    who = email or f"you@{allowed_email_domain()}"
    return (
        "On the Jetson (no password in git): "
        f"./scripts/hawkeye accounts set-password --email {who}"
    )


def diagnose_login(username: str, password: str) -> LoginFailure | None:
    """Explain why a login would fail. None means credentials are acceptable.

    Ignores AUTOCODE_PRIVATE_MODE so `hawkeye accounts check` works on a
    checkout that has users.json but has not exported private-mode env.
    """
    if not (username or "").strip() or not password:
        return LoginFailure(
            CODE_EMPTY,
            "Email and password required "
            "(browser autofill may have left the password empty — type it, then Show).",
            "Use your @%s work email. Local part only (e.g. mark) is fine."
            % allowed_email_domain(),
        )
    if not credentials_ready():
        return LoginFailure(
            CODE_NOT_CONFIGURED,
            "No Hawkeye work users are configured on this machine.",
            _reset_hint(),
        )
    email = canonicalize_email(username)
    if not is_allowed_email(email):
        return LoginFailure(
            CODE_BAD_DOMAIN,
            f"Only @{allowed_email_domain()} work emails can sign in to Hawkeye.",
            "This is the app login, not Cloudflare Access. "
            "Personal Gmail/Outlook addresses are rejected here.",
        )
    users = load_users()
    stored = users.get(email)
    if not stored:
        return LoginFailure(
            CODE_UNKNOWN_ACCOUNT,
            f"No Hawkeye account for {email}.",
            _reset_hint(email),
        )
    if not verify_password(password, stored):
        return LoginFailure(
            CODE_WRONG_PASSWORD,
            f"Wrong password for {email}.",
            "Try Show password to check typos, or ask an admin to reset it. "
            + _reset_hint(email),
        )
    return None


def authenticate(username: str, password: str) -> tuple[str | None, LoginFailure | None]:
    """Return (session_token, None) on success, else (None, LoginFailure)."""
    if not private_mode_enabled():
        return secrets.token_urlsafe(24), None
    failure = diagnose_login(username, password)
    if failure:
        return None, failure
    email = canonicalize_email(username)
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "user": email,
        "exp": time.time() + SESSION_TTL_SEC,
    }
    return token, None


def login(username: str, password: str) -> str | None:
    """Return session token on success, else None.

    `username` is treated as a work email (case-insensitive).
    """
    token, _failure = authenticate(username, password)
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
    """First-party session cookie.

    SameSite=Lax is correct behind Cloudflare Tunnel (same site as the form).
    Secure is required on HTTPS; omitting it on loopback HTTP is required or
    browsers drop the cookie and login silently redirects back to /login.
    Do not set Domain= — default host-only scoping avoids sharing across
    sibling subdomains.
    """
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


def clear_session_cookie_header(secure: bool = False) -> str:
    # Must match Path / SameSite / Secure of the original cookie or browsers
    # keep the session and logout (or a failed retry) looks broken.
    parts = [
        f"{COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def cloudflare_access_identity(headers: Any) -> dict[str, Any]:
    """Detect a Cloudflare Access (Zero Trust) identity from request headers.

    Production hawkeye.brownhawke.engineering (2026-09-19) is Tunnel + proxy
    only — no CF-Access-* headers. If Access is added later, the login page
    should say so instead of looking like a bad Hawkeye password.
    """
    if headers is None:
        return {"cloudflare_access": False, "access_email": None}

    def _get(name: str) -> str:
        if hasattr(headers, "get"):
            val = headers.get(name) or headers.get(name.lower()) or ""
        else:
            val = ""
        return str(val).strip()

    access_email = (
        _get("Cf-Access-Authenticated-User-Email")
        or _get("Cf-Access-Authenticated-User-Email".lower())
    )
    jwt = _get("Cf-Access-Jwt-Assertion") or _get("Cf-Access-Jwt-Assertion".lower())
    return {
        "cloudflare_access": bool(access_email or jwt),
        "access_email": access_email or None,
    }
