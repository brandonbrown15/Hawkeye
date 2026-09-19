"""WhatsApp E.164 allowlist — same vault field the webhook already reads.

Empty list rejects all inbound and outbound (safe default). The UI Add/Remove
editor persists comma-joined digits to Connections `allowed_numbers`.
"""

from __future__ import annotations

from typing import Any

from whatsapp import config

EXAMPLE_NUMBER = "447710086970"
EXAMPLE_E164 = "+447710086970"
EXAMPLE_LABEL = "Brandon"
EMPTY_SENTINEL = "-"


def format_e164(raw: str) -> str:
    digits = config.normalize_number(raw)
    return f"+{digits}" if digits else ""


def validate_number(raw: str) -> str:
    digits = config.normalize_number(raw)
    if len(digits) < 8:
        raise ValueError(f"Enter a full E.164 number (e.g. {EXAMPLE_E164})")
    return digits


def join_numbers(numbers: list[str]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for raw in numbers:
        digits = config.normalize_number(raw)
        if len(digits) >= 8 and digits not in seen:
            seen.add(digits)
            out.append(digits)
    return ",".join(out) if out else EMPTY_SENTINEL


def current_numbers(*, email: str | None = None) -> list[str]:
    return config.parse_number_list(config.secret("allowed_numbers", email=email))


def persist(email: str, numbers: list[str]) -> dict[str, Any]:
    from ui import connections

    blob = join_numbers(numbers)
    listed = connections.set_connection(email, "whatsapp", secrets={"allowed_numbers": blob})
    listed["allowed_numbers"] = [] if blob == EMPTY_SENTINEL else config.parse_number_list(blob)
    listed["ok"] = True
    return listed


def add_number(email: str, raw: str) -> dict[str, Any]:
    digits = validate_number(raw)
    nums = current_numbers(email=email)
    added = digits not in nums
    if added:
        nums.append(digits)
    out = persist(email, nums)
    out["added"] = digits
    out["changed"] = added
    return out


def remove_number(email: str, raw: str) -> dict[str, Any]:
    digits = config.normalize_number(raw)
    if not digits:
        raise ValueError("number required")
    before = current_numbers(email=email)
    nums = [n for n in before if n != digits]
    out = persist(email, nums)
    out["removed"] = digits
    out["changed"] = nums != before
    return out
