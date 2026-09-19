"""Resolve WhatsApp Cloud API settings from Connections vault or machine .env."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

WEBHOOK_PATH = "/api/webhooks/whatsapp"
DEFAULT_NOTIFY_RULES = ("queue_empty", "blocked", "human")
OPTIONAL_NOTIFY_RULES = ("digest",)
ALL_NOTIFY_RULES = DEFAULT_NOTIFY_RULES + OPTIONAL_NOTIFY_RULES

# Map notify kinds used by callers → rule name.
KIND_RULES = {
    "queue_empty": "queue_empty",
    "ready_drained": "queue_empty",
    "blocked": "blocked",
    "human": "human",
    "awaiting_operator": "human",
    "digest": "digest",
    "test": "test",
}


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def owner_email() -> str:
    """Vault email for overnight / webhook (no HTTP session)."""
    explicit = os.environ.get("HAWKEYE_WHATSAPP_USER", "").strip()
    if explicit:
        return explicit
    auto = os.environ.get("HAWKEYE_AUTOPILOT_EMAIL", "").strip()
    if auto:
        return auto
    admins = os.environ.get("HAWKEYE_ADMIN_EMAILS", "")
    first = next((x.strip() for x in admins.split(",") if x.strip()), "")
    return first or "brandon@brownhawke.engineering"


def secret(field: str, *, email: str | None = None) -> str:
    """Prefer operator vault, then machine .env."""
    try:
        from ui import connections

        val = connections.resolve_secret("whatsapp", field, email=email or owner_email())
        if val:
            return val
        return connections.resolve_secret("whatsapp", field)
    except Exception:  # noqa: BLE001
        pass
    env_map = {
        "phone_number_id": ("WHATSAPP_PHONE_NUMBER_ID", "HAWKEYE_WHATSAPP_PHONE_NUMBER_ID"),
        "access_token": ("WHATSAPP_ACCESS_TOKEN", "HAWKEYE_WHATSAPP_ACCESS_TOKEN"),
        "verify_token": ("WHATSAPP_VERIFY_TOKEN", "HAWKEYE_WHATSAPP_VERIFY_TOKEN"),
        "app_secret": ("WHATSAPP_APP_SECRET", "HAWKEYE_WHATSAPP_APP_SECRET"),
        "allowed_numbers": ("WHATSAPP_ALLOWED_NUMBERS", "HAWKEYE_WHATSAPP_ALLOWED_NUMBERS"),
        "notify_rules": ("HAWKEYE_WHATSAPP_NOTIFY_RULES",),
    }
    for key in env_map.get(field, ()):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def public_webhook_url() -> str:
    try:
        from ui import auth as ui_auth

        host = ui_auth.public_host()
    except Exception:  # noqa: BLE001
        host = os.environ.get("AUTOCODE_PUBLIC_HOST") or "hawkeye.brownhawke.engineering"
    host = host.strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        return f"{host}{WEBHOOK_PATH}"
    return f"https://{host}{WEBHOOK_PATH}"


def graph_version() -> str:
    raw = os.environ.get("HAWKEYE_WHATSAPP_GRAPH_VERSION", "v21.0").strip() or "v21.0"
    return raw if raw.startswith("v") else f"v{raw}"


def graph_messages_url(phone_number_id: str | None = None) -> str:
    pid = (phone_number_id or secret("phone_number_id")).strip()
    return f"https://graph.facebook.com/{graph_version()}/{pid}/messages"


def enabled() -> bool:
    if not _truthy("HAWKEYE_WHATSAPP_ENABLED", "1"):
        return False
    return bool(secret("access_token") and secret("phone_number_id"))


def normalize_number(raw: str) -> str:
    """Digits-only E.164 (WhatsApp Cloud API omits '+')."""
    return re.sub(r"\D", "", raw or "")


def parse_number_list(raw: str) -> list[str]:
    """Split on comma/semicolon only so '+1 (555) 123-4567' stays one number."""
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;]+", raw or ""):
        digits = normalize_number(part)
        # E.164 is at least country code + subscriber (reject leftover fragments).
        if len(digits) >= 8 and digits not in seen:
            seen.add(digits)
            out.append(digits)
    return out


def allowed_numbers() -> list[str]:
    return parse_number_list(secret("allowed_numbers"))


def number_allowed(phone: str) -> bool:
    """Strict allowlist. Empty list = reject everyone (safe default)."""
    want = normalize_number(phone)
    if not want:
        return False
    allowed = allowed_numbers()
    return want in allowed


def parse_notify_rules(raw: str | None = None) -> set[str]:
    text = (raw if raw is not None else secret("notify_rules")).strip().lower()
    if not text:
        rules = set(DEFAULT_NOTIFY_RULES)
    else:
        rules = {p.strip() for p in text.split(",") if p.strip()}
        rules.discard("")
    # Per-rule env overrides (1/0) win over the list.
    env_keys = {
        "queue_empty": "HAWKEYE_WHATSAPP_NOTIFY_QUEUE_EMPTY",
        "blocked": "HAWKEYE_WHATSAPP_NOTIFY_BLOCKED",
        "human": "HAWKEYE_WHATSAPP_NOTIFY_HUMAN",
        "digest": "HAWKEYE_WHATSAPP_NOTIFY_DIGEST",
    }
    for rule, key in env_keys.items():
        if key not in os.environ:
            continue
        if _truthy(key, "0"):
            rules.add(rule)
        else:
            rules.discard(rule)
    return rules


def notify_rule_enabled(kind: str) -> bool:
    if kind == "test":
        return True
    rule = KIND_RULES.get(kind, kind)
    return rule in parse_notify_rules()


def data_dir() -> Path:
    raw = os.environ.get("HAWKEYE_WHATSAPP_DIR", "").strip()
    if raw:
        path = Path(raw)
    else:
        root = os.environ.get("AUTOCODE_DATA_ROOT", "").strip()
        if root:
            path = Path(root) / "hawkeye" / "whatsapp"
        else:
            path = Path(__file__).resolve().parents[1] / "state" / "whatsapp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def connection_public_fields() -> dict[str, Any]:
    return {
        "webhook_url": public_webhook_url(),
        "webhook_path": WEBHOOK_PATH,
    }
