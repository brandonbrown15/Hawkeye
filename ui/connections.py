"""Per-user integration connections (encrypted secrets at rest).

Secrets stored under accounts/connections/<email>.json using memory crypto
(HAWKEYE_MEMORY_KEY / HAWKEYE_SECRETS_KEY). APIs never return raw secrets.

Runtime callers use resolve_secret() — prefers the signed-in user's vault,
then falls back to machine .env so overnight autopilot still works.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ui import accounts
from ui import auth as ui_auth

_LOCK = threading.RLock()
_REQUEST_USER: ContextVar[str | None] = ContextVar("hawkeye_request_user", default=None)

PROVIDERS = (
    "cloudflare",
    "notion",
    "github",
    "cursor",
    "claude",
    "chatgpt",
    "grok",
    "openrouter",
    "brave",
    "telegram",
    "whatsapp",
)

# Maps UI fields → machine .env fallbacks (first non-empty wins).
ENV_FALLBACKS: dict[tuple[str, str], tuple[str, ...]] = {
    ("cloudflare", "api_token"): ("CLOUDFLARE_API_TOKEN",),
    ("cloudflare", "account_id"): ("CLOUDFLARE_ACCOUNT_ID",),
    ("notion", "token"): ("NOTION_TOKEN",),
    ("github", "token"): ("GITHUB_TOKEN", "GH_TOKEN"),
    ("cursor", "api_key"): ("CURSOR_API_KEY",),
    ("cursor", "repository"): ("CURSOR_REPOSITORY", "HAWKEYE_CURSOR_REPO", "CURSOR_REPO_URL"),
    ("cursor", "webhook_url"): ("CURSOR_WEBHOOK_URL",),
    ("cursor", "webhook_token"): ("CURSOR_WEBHOOK_TOKEN", "CURSOR_API_KEY"),
    ("claude", "api_key"): ("ANTHROPIC_API_KEY",),
    ("chatgpt", "api_key"): ("OPENAI_API_KEY",),
    ("chatgpt", "org_id"): ("OPENAI_ORG_ID",),
    ("grok", "webhook_url"): ("GROK_BOT_WEBHOOK_URL",),
    ("grok", "webhook_token"): ("GROK_BOT_WEBHOOK_TOKEN",),
    ("grok", "api_key"): ("XAI_API_KEY",),
    ("openrouter", "api_key"): ("OPENROUTER_API_KEY",),
    ("brave", "api_key"): ("BRAVE_SEARCH_API_KEY",),
    ("telegram", "bot_token"): ("TELEGRAM_BOT_TOKEN",),
    ("telegram", "chat_id"): ("TELEGRAM_CHAT_ID",),
    ("whatsapp", "phone_number_id"): (
        "WHATSAPP_PHONE_NUMBER_ID",
        "HAWKEYE_WHATSAPP_PHONE_NUMBER_ID",
    ),
    ("whatsapp", "access_token"): (
        "WHATSAPP_ACCESS_TOKEN",
        "HAWKEYE_WHATSAPP_ACCESS_TOKEN",
    ),
    ("whatsapp", "verify_token"): (
        "WHATSAPP_VERIFY_TOKEN",
        "HAWKEYE_WHATSAPP_VERIFY_TOKEN",
    ),
    ("whatsapp", "app_secret"): (
        "WHATSAPP_APP_SECRET",
        "HAWKEYE_WHATSAPP_APP_SECRET",
    ),
    ("whatsapp", "allowed_numbers"): (
        "WHATSAPP_ALLOWED_NUMBERS",
        "HAWKEYE_WHATSAPP_ALLOWED_NUMBERS",
    ),
    ("whatsapp", "notify_rules"): ("HAWKEYE_WHATSAPP_NOTIFY_RULES",),
}

PROVIDER_META = {
    "cloudflare": {
        "label": "Cloudflare",
        "fields": ["api_token", "account_id"],
        "hint": "API token (DNS / Workers / Tunnel scopes). Tunnel install token is under Machine.",
    },
    "notion": {
        "label": "Notion",
        "fields": ["token"],
        "hint": "Internal integration token — used for live PM boards in your session",
    },
    "github": {
        "label": "GitHub",
        "fields": ["token"],
        "hint": "Fine-grained or classic PAT with repo access — also powers Jetson auto-update HTTPS fetch",
    },
    "cursor": {
        "label": "Cursor",
        "fields": ["api_key", "repository", "webhook_url", "webhook_token"],
        "connect_fields": ["api_key", "webhook_url"],
        "public_fields": ["repository"],
        "hint": (
            "API key from Cursor Dashboard → API Keys (starts Cloud Agents). "
            "Optional repository = https://github.com/org/repo for coding agents. "
            "webhook_url is only for a custom bridge (optional)."
        ),
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "fields": ["api_key"],
        "hint": "Anthropic API key for Claude escalate",
    },
    "chatgpt": {
        "label": "ChatGPT / Codex",
        "fields": ["api_key", "org_id"],
        "hint": "OpenAI API key for ChatGPT / Codex",
    },
    "grok": {
        "label": "Grok Bot / xAI",
        "fields": ["webhook_url", "webhook_token", "api_key"],
        "hint": "Grok Bot webhook and/or xAI API key",
    },
    "openrouter": {
        "label": "OpenRouter",
        "fields": ["api_key"],
        "hint": "OpenRouter API key (cloud escalate fallback)",
    },
    "brave": {
        "label": "Brave Search",
        "fields": ["api_key"],
        "hint": (
            "Brave Search API key for chat web search when Local only is off "
            "(DuckDuckGo HTML is the fallback if no key). Local only blocks all external web."
        ),
    },
    "telegram": {
        "label": "Telegram",
        "fields": ["bot_token", "chat_id"],
        "public_fields": ["chat_id"],
        "hint": "Bot token + chat id for digests / alerts",
    },
    "whatsapp": {
        "label": "WhatsApp (Cloud API)",
        "fields": [
            "phone_number_id",
            "access_token",
            "verify_token",
            "app_secret",
            "allowed_numbers",
            "notify_rules",
        ],
        "connect_fields": ["access_token", "phone_number_id"],
        "public_fields": ["phone_number_id", "notify_rules"],
        "list_fields": ["allowed_numbers"],
        "webhook_path": "/api/webhooks/whatsapp",
        "hint": (
            "Official Meta WhatsApp Cloud API. Save phone number id + access token + "
            "verify token + app secret. Add Brandon's WhatsApp (+447710086970) on the "
            "allowlist — empty list rejects everyone. "
            "notify_rules default: queue_empty,blocked,human (add digest to opt in)."
        ),
    },
}


def set_request_user(email: str | None) -> None:
    """Bind the signed-in email for resolve_secret() during a request."""
    _REQUEST_USER.set(ui_auth.normalize_email(email) if email else None)


def get_request_user() -> str | None:
    return _REQUEST_USER.get()


def _safe_email_file(email: str) -> str:
    email = ui_auth.normalize_email(email)
    return re.sub(r"[^a-z0-9._-]+", "_", email)


def connections_path(email: str) -> Path:
    return accounts.accounts_root() / "connections" / f"{_safe_email_file(email)}.json"


def _secrets_key() -> bytes | None:
    raw = os.environ.get("HAWKEYE_SECRETS_KEY", "").strip()
    if raw:
        os.environ.setdefault("HAWKEYE_MEMORY_KEY", raw)
    try:
        from memory import crypto

        return crypto.memory_key()
    except Exception:  # noqa: BLE001
        return None


def _encrypt_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    key = _secrets_key()
    if key is None:
        raise ValueError(
            "Set HAWKEYE_MEMORY_KEY (Account → Machine) before saving connection secrets. "
            "Plaintext secret storage is not allowed."
        )
    try:
        from memory import crypto

        return crypto.encode_record({"v": value}, key)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not encrypt secret: {e}") from e


def _decrypt_secret(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        return ""
    # Legacy plaintext blobs are never returned — re-save after setting MEMORY_KEY.
    if blob.startswith("plain:"):
        return ""
    try:
        from memory import crypto

        obj = crypto.decode_record(blob, _secrets_key())
        return str(obj.get("v") or "")
    except Exception:  # noqa: BLE001
        return ""


def _load(email: str) -> dict[str, Any]:
    path = connections_path(email)
    if not path.is_file():
        return {"email": ui_auth.normalize_email(email), "providers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"email": ui_auth.normalize_email(email), "providers": {}}
    if not isinstance(data, dict):
        return {"email": ui_auth.normalize_email(email), "providers": {}}
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    return {"email": ui_auth.normalize_email(email), "providers": providers, "updated_at": data.get("updated_at")}


def _save(email: str, data: dict[str, Any]) -> None:
    path = connections_path(email)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["email"] = ui_auth.normalize_email(email)
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_connections(email: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load(email)
    out: dict[str, Any] = {}
    for pid in PROVIDERS:
        meta = PROVIDER_META[pid]
        row = (data.get("providers") or {}).get(pid) or {}
        secrets = row.get("secrets") if isinstance(row.get("secrets"), dict) else {}
        connect_fields = meta.get("connect_fields") or meta["fields"]
        saved_fields, unreadable_fields = _classify_vault_fields(secrets, meta["fields"])
        # Connected only if a connect-field actually decrypts. Blob presence alone
        # used to mark Connected while chat escalate saw empty secrets ([none]).
        connected = any(f in saved_fields for f in connect_fields)
        unreadable = (not connected) and any(f in unreadable_fields for f in connect_fields)
        # Show machine-env fallback as "machine" so operators know autopilot still works.
        machine = False
        if not connected:
            for field in connect_fields:
                if _env_fallback(pid, field):
                    machine = True
                    break
        if connected:
            status = "connected"
        elif unreadable:
            status = "unreadable"
        elif machine:
            status = "machine"
        else:
            status = "disconnected"
        item = {
            "id": pid,
            "label": meta["label"],
            "hint": meta["hint"],
            "fields": meta["fields"],
            "public_fields": list(meta.get("public_fields") or []),
            "status": status,
            "account_label": str(row.get("account_label") or ""),
            "updated_at": row.get("updated_at"),
            "has_secret": connected,
            "saved_fields": saved_fields,
            "unreadable_fields": unreadable_fields,
            "machine_fallback": machine,
            "encryption": "on" if _secrets_key() else "off",
        }
        webhook_path = str(meta.get("webhook_path") or "")
        if webhook_path:
            item["webhook_url"] = f"https://{ui_auth.public_host()}{webhook_path}"
            item["webhook_path"] = webhook_path
        list_fields = list(meta.get("list_fields") or [])
        if list_fields:
            item["list_fields"] = list_fields
        if pid == "whatsapp":
            raw_allow = get_secret(email, "whatsapp", "allowed_numbers") or _env_fallback(
                "whatsapp", "allowed_numbers"
            )
            try:
                from whatsapp.allowlist import EXAMPLE_E164
                from whatsapp.config import parse_number_list

                item["allowed_numbers"] = parse_number_list(raw_allow)
                item["allowed_numbers_example"] = EXAMPLE_E164
            except Exception:  # noqa: BLE001
                item["allowed_numbers"] = []
                item["allowed_numbers_example"] = "+447710086970"
        out[pid] = item
    return {
        "ok": True,
        "email": email,
        "providers": out,
        "encryption_ready": bool(_secrets_key()),
    }


def set_connection(
    email: str,
    provider: str,
    *,
    secrets: dict[str, str] | None = None,
    account_label: str | None = None,
) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    secrets = secrets or {}
    with _LOCK:
        data = _load(email)
        providers = dict(data.get("providers") or {})
        row = dict(providers.get(provider) or {})
        enc_secrets = dict(row.get("secrets") or {}) if isinstance(row.get("secrets"), dict) else {}
        for field in PROVIDER_META[provider]["fields"]:
            if field in secrets and secrets[field] is not None:
                val = str(secrets[field]).strip()
                if val:
                    enc_secrets[field] = _encrypt_secret(val)
                else:
                    enc_secrets.pop(field, None)
        row["secrets"] = enc_secrets
        if account_label is not None:
            row["account_label"] = account_label.strip()
        row["updated_at"] = time.time()
        providers[provider] = row
        data["providers"] = providers
        _save(email, data)
    # Machine auto-update timer only sees .env — mirror GitHub PAT for HTTPS fetch.
    if provider == "github" and secrets.get("token"):
        try:
            from ui import machine_settings

            machine_settings.sync_github_token_from_connections(email)
        except Exception:  # noqa: BLE001
            pass
    return list_connections(email)


def disconnect(email: str, provider: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    with _LOCK:
        data = _load(email)
        providers = dict(data.get("providers") or {})
        providers.pop(provider, None)
        data["providers"] = providers
        _save(email, data)
    return list_connections(email)


def get_secret(email: str, provider: str, field: str) -> str:
    """Internal use only — decrypt a stored secret for the signed-in user."""
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load(email)
        row = (data.get("providers") or {}).get(provider) or {}
        secrets = row.get("secrets") if isinstance(row.get("secrets"), dict) else {}
        return _decrypt_secret(str(secrets.get(field) or ""))


def _classify_vault_fields(secrets: dict[str, Any], fields: list[str]) -> tuple[list[str], list[str]]:
    """Split vault blobs into decryptable vs ciphertext we cannot read."""
    saved: list[str] = []
    unreadable: list[str] = []
    for field in fields:
        blob = secrets.get(field)
        if not blob:
            continue
        if _decrypt_secret(str(blob)):
            saved.append(field)
        else:
            unreadable.append(field)
    return saved, unreadable


def unreadable_secret_labels(
    *,
    email: str | None = None,
    providers: tuple[str, ...] | None = None,
) -> list[str]:
    """Labels like cursor.api_key when a vault blob exists but will not decrypt."""
    email = ui_auth.normalize_email(email) if email else get_request_user()
    if not email:
        return []
    labels: list[str] = []
    with _LOCK:
        data = _load(email)
    for pid in providers or PROVIDERS:
        meta = PROVIDER_META.get(pid) or {}
        row = (data.get("providers") or {}).get(pid) or {}
        secrets = row.get("secrets") if isinstance(row.get("secrets"), dict) else {}
        _, unread = _classify_vault_fields(secrets, list(meta.get("fields") or secrets.keys()))
        labels.extend(f"{pid}.{field}" for field in unread)
    return labels


def _env_fallback(provider: str, field: str) -> str:
    for key in ENV_FALLBACKS.get((provider, field), ()):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def resolve_secret(
    provider: str,
    field: str,
    *,
    email: str | None = None,
    env_keys: tuple[str, ...] | None = None,
) -> str:
    """Prefer per-user vault, then machine .env (for autopilot / shared tokens)."""
    provider = (provider or "").strip().lower()
    field = (field or "").strip()
    email = ui_auth.normalize_email(email) if email else get_request_user()
    if email:
        val = get_secret(email, provider, field)
        if val:
            return val
    if env_keys:
        for key in env_keys:
            val = os.environ.get(key, "").strip()
            if val:
                return val
    return _env_fallback(provider, field)


def has_secret(provider: str, field: str, *, email: str | None = None) -> bool:
    return bool(resolve_secret(provider, field, email=email))
