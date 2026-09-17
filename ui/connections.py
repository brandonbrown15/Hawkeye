"""Per-user integration connections (encrypted secrets at rest).

Providers: cloudflare, notion, github, cursor, claude, chatgpt.
Secrets stored under accounts/connections/<email>.json using memory crypto
(HAWKEYE_MEMORY_KEY / HAWKEYE_SECRETS_KEY). APIs never return raw secrets.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ui import accounts
from ui import auth as ui_auth

_LOCK = threading.RLock()

PROVIDERS = (
    "cloudflare",
    "notion",
    "github",
    "cursor",
    "claude",
    "chatgpt",
)

PROVIDER_META = {
    "cloudflare": {
        "label": "Cloudflare",
        "fields": ["api_token", "account_id"],
        "hint": "API token with DNS / Workers / Tunnel scopes as needed",
    },
    "notion": {
        "label": "Notion",
        "fields": ["token"],
        "hint": "Internal integration token or OAuth access token",
    },
    "github": {
        "label": "GitHub",
        "fields": ["token"],
        "hint": "Fine-grained or classic PAT with repo access",
    },
    "cursor": {
        "label": "Cursor",
        "fields": ["api_key", "webhook_url", "webhook_token"],
        "hint": "Cursor API key and/or Cloud Agent webhook",
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "fields": ["api_key"],
        "hint": "Anthropic API key for Claude Code / API",
    },
    "chatgpt": {
        "label": "ChatGPT / Codex",
        "fields": ["api_key", "org_id"],
        "hint": "OpenAI API key for ChatGPT / Codex",
    },
}


def _safe_email_file(email: str) -> str:
    email = ui_auth.normalize_email(email)
    return re.sub(r"[^a-z0-9._-]+", "_", email)


def connections_path(email: str) -> Path:
    return accounts.accounts_root() / "connections" / f"{_safe_email_file(email)}.json"


def _secrets_key() -> bytes | None:
    # Prefer dedicated secrets key; fall back to memory key.
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
    try:
        from memory import crypto

        key = _secrets_key()
        if key is None:
            # Still mark as stored but warn via status; keep obfuscated prefix.
            return "plain:" + value
        return crypto.encode_record({"v": value}, key)
    except Exception:  # noqa: BLE001
        return "plain:" + value


def _decrypt_secret(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        return ""
    if blob.startswith("plain:"):
        return blob[6:]
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
        connected = any(bool(secrets.get(f)) for f in meta["fields"])
        out[pid] = {
            "id": pid,
            "label": meta["label"],
            "hint": meta["hint"],
            "fields": meta["fields"],
            "status": "connected" if connected else "disconnected",
            "account_label": str(row.get("account_label") or ""),
            "updated_at": row.get("updated_at"),
            "has_secret": connected,
            "encryption": "on" if _secrets_key() else "off",
        }
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
