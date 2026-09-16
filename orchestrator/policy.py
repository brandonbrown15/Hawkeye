#!/usr/bin/env python3
"""Cost-aware, task-dependent model routing for Autocode.

Research note (2026): direct xAI / Grok Bot API is often the *most expensive*
path for agent loops (long context + many tool turns). Cursor Ultra (~$200/mo)
includes Grok in the Cursor Models pool — use that instead of XAI_API_KEY.
Claude Code Max ($100–200/mo) is optional if you consolidate on Ultra.

Tier ladder is cheap → expensive cloud spend, overridable via:
  AUTOCODE_COST_PROFILE  or  AUTOCODE_COST_LADDER
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


# Profiles ranked by *effective overnight spend* (not raw $/MTok sticker price).
# Direct xAI/OpenRouter Grok API is last / omitted — agent loops rack up bills fast.
# "Grok Bot" here means your webhook / Telegram / SuperGrok agent launcher
# (AUTOCODE_GROK_DELEGATE_CMD), not uncapped XAI_API_KEY.
COST_PROFILES: dict[str, tuple[str, ...]] = {
    # Cursor Ultra + Grok Bot: cheaper Ultra pool first, then your Grok Bot.
    # Swap with AUTOCODE_CLOUD_PREFERENCE=grok if Bot is the flatter plan.
    "cursor-grok": ("Cursor Cloud", "Grok Bot", "Human"),
    # Pay Cursor Ultra only; drop Claude Code + raw xAI. Grok via Cursor Models.
    "cursor-ultra": ("Cursor Cloud", "Human"),
    # Keep Claude Max as mid; Cursor for heavy; no metered Grok.
    "claude-max": ("Claude", "Cursor Cloud", "Human"),
    # Pay-as-you-go APIs — Claude before Cursor; metered Grok last resort.
    "metered": ("Claude", "Cursor Cloud", "Grok Bot", "Human"),
    # Default after cost research: Cursor + Grok Bot (no Claude required).
    "default": ("Cursor Cloud", "Grok Bot", "Human"),
}

DEFAULT_LADDER = COST_PROFILES["default"]

# Explicit Notion Model route overrides always win.
ROUTE_ALIASES = {
    "Local Hermes": "local",
    "local": "local",
    "Grok": "Grok Bot",
    "Grok Bot": "Grok Bot",
    "Claude": "Claude",
    "Cursor Cloud": "Cursor Cloud",
    "Human": "Human",
}

HEAVY_KEYWORDS = (
    "auth",
    "oauth",
    "billing",
    "payment",
    "infra",
    "kubernetes",
    "k8s",
    "terraform",
    "security",
    "migration",
    "architecture",
    "refactor",
    "multi-repo",
    "database schema",
    "prod",
    "production",
    "incident",
)


@dataclass(frozen=True)
class RouteDecision:
    target: str
    tier: str  # local | cheap | standard | premium | human
    reason: str
    score: int


def _prefer_grok_first() -> bool:
    return (os.environ.get("AUTOCODE_CLOUD_PREFERENCE", "cursor") or "cursor").strip().lower() in (
        "grok",
        "grok-bot",
        "grok_bot",
    )


def _ladder() -> list[str]:
    """Resolve ladder: explicit AUTOCODE_COST_LADDER wins, else profile (+ preference)."""
    raw = os.environ.get("AUTOCODE_COST_LADDER", "")
    if raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            return parts
    profile = (os.environ.get("AUTOCODE_COST_PROFILE", "default") or "default").strip().lower()
    ladder = list(COST_PROFILES.get(profile, COST_PROFILES["default"]))
    # Optional swap: put Grok Bot before Cursor when Bot is the cheaper flat plan.
    if _prefer_grok_first() and "Grok Bot" in ladder and "Cursor Cloud" in ladder:
        reordered: list[str] = []
        for name in ("Grok Bot", "Cursor Cloud"):
            if name in ladder and name not in reordered:
                reordered.append(name)
        for item in ladder:
            if item not in reordered:
                reordered.append(item)
        return reordered
    return ladder


def _available(target: str) -> bool:
    if target == "local":
        return True
    if target == "Human":
        return True
    if target == "Grok Bot":
        # Custom Bot webhook / Telegram launcher = OK (flat SuperGrok / your bot).
        if os.environ.get("AUTOCODE_GROK_DELEGATE_CMD"):
            return True
        # Raw xAI/OpenRouter meters are opt-in expensive.
        if os.environ.get("AUTOCODE_DISABLE_METERED_GROK", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            return False
        return bool(
            os.environ.get("XAI_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
        )
    if target == "Claude":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if target == "Cursor Cloud":
        return bool(
            os.environ.get("AUTOCODE_CURSOR_DELEGATE_CMD")
            or os.environ.get("CURSOR_API_KEY")
        )
    return False


def _first_available(candidates: list[str], assume_keys: bool = False) -> str:
    """Pick first candidate that is configured. If assume_keys, skip availability checks (tests)."""
    for c in candidates:
        if c == "local" or c == "Human" or assume_keys or _available(c):
            return c
    return "Human"


def _cloud_slots(ladder: list[str]) -> list[str]:
    return [x for x in ladder if x != "Human"]


def _text_blob(task: Any) -> str:
    parts = [
        getattr(task, "name", "") or "",
        getattr(task, "acceptance", "") or "",
        getattr(task, "notes", "") or "",
    ]
    return " ".join(parts).lower()


def score_task(task: Any) -> int:
    """Higher score ⇒ heavier task (may need a stronger cloud model).

    Rough scale:
      0–29  local (Jetson / Hermes)
      30–49  light cloud
      50–69  mid cloud
      70+    heavy cloud
    Which *provider* fills each slot comes from the cost ladder / profile.
    """
    score = 0
    complexity = (getattr(task, "complexity", "") or "").strip()
    priority = (getattr(task, "priority", "") or "").strip().upper()
    model_route = (getattr(task, "model_route", "") or "").strip()

    if complexity == "Local-safe":
        score += 10
    elif complexity == "Maybe local":
        score += 40
    elif complexity == "Cloud-only":
        # Mid by default; P0 / heavy keywords push into premium
        score += 55
    else:
        score += 35

    if priority in ("P0", "0"):
        score += 25
    elif priority in ("P1", "1"):
        score += 15
    elif priority in ("P2", "2"):
        score += 5

    blob = _text_blob(task)
    hits = sum(1 for kw in HEAVY_KEYWORDS if kw in blob)
    score += min(30, hits * 10)

    if model_route and model_route not in ("Local Hermes", "local"):
        score = max(score, 55)

    return score


def tier_for_score(score: int) -> str:
    if score < 30:
        return "local"
    if score < 50:
        return "cheap"
    if score < 70:
        return "standard"
    return "premium"


def _order_for_tier(tier: str, cloud: list[str]) -> list[str]:
    """Map semantic tiers onto providers.

    Ladder order is cost order. Premium (hard) work prefers Cursor capability
    when present. Grok Bot stays in its ladder slot for cheap/standard — it is
    only last among *premium fallbacks* when other options exist.
    """
    if len(cloud) == 1:
        return [cloud[0], "Human"]

    cheap = cloud[0]
    mid = cloud[1] if len(cloud) > 1 else cheap

    if tier == "cheap":
        return cloud + ["Human"]
    if tier == "standard":
        others = [c for c in cloud if c != mid]
        return [mid] + others + ["Human"]
    if tier == "premium":
        preferred: list[str] = []
        for name in ("Cursor Cloud", "Claude", "Grok Bot"):
            if name in cloud and name not in preferred:
                preferred.append(name)
        for c in cloud:
            if c not in preferred:
                preferred.append(c)
        return preferred + ["Human"]
    return ["Human"]


def target_for_tier(tier: str, assume_keys: bool = False) -> str:
    ladder = _ladder()
    cloud = _cloud_slots(ladder)
    if not cloud:
        return "Human"
    if tier == "local":
        return "local"
    return _first_available(_order_for_tier(tier, cloud), assume_keys=assume_keys)


def decide_route(
    task: Any,
    *,
    local_failures: int = 0,
    hardware_constrained: bool = False,
    local_stack_ok: bool = True,
    assume_keys: bool = False,
    max_local_attempts: int = 2,
) -> RouteDecision:
    """Return the model/target for this task under a cost-saving policy."""
    model_route = (getattr(task, "model_route", "") or "").strip()
    complexity = (getattr(task, "complexity", "") or "").strip()

    # 1) Explicit Model route always wins (operator override)
    if model_route and model_route not in ("Local Hermes", "local"):
        target = ROUTE_ALIASES.get(model_route, model_route)
        return RouteDecision(
            target=target,
            tier="premium" if target == "Cursor Cloud" else "standard",
            reason=f"explicit Model route={model_route}",
            score=score_task(task),
        )

    score = score_task(task)
    tier = tier_for_score(score)

    # 2) Force escalate when local cannot run
    if hardware_constrained or not local_stack_ok or local_failures >= max_local_attempts:
        if tier == "local":
            tier = "cheap"
        reason_bits = []
        if hardware_constrained:
            reason_bits.append("hardware constrained")
        if not local_stack_ok:
            reason_bits.append("local stack unhealthy")
        if local_failures >= max_local_attempts:
            reason_bits.append(f"local failures={local_failures}")
        target = target_for_tier(tier, assume_keys=assume_keys)
        return RouteDecision(
            target=target,
            tier=tier,
            reason=f"escalate ({', '.join(reason_bits)}); score={score}",
            score=score,
        )

    # 3) Cloud-only never stays local
    if complexity == "Cloud-only":
        if tier == "local":
            tier = "standard"
        target = target_for_tier(tier, assume_keys=assume_keys)
        return RouteDecision(
            target=target,
            tier=tier,
            reason=f"Cloud-only; score={score} → {tier}",
            score=score,
        )

    # 4) Normal cost ladder
    if tier == "local":
        return RouteDecision(
            target="local",
            tier="local",
            reason=f"Local-safe / low score={score}",
            score=score,
        )

    if complexity == "Maybe local" and score < 55:
        return RouteDecision(
            target="local",
            tier="local",
            reason=f"Maybe local; try local first (score={score})",
            score=score,
        )

    target = target_for_tier(tier, assume_keys=assume_keys)
    return RouteDecision(
        target=target,
        tier=tier,
        reason=f"score={score} → tier={tier}",
        score=score,
    )


def describe_policy() -> str:
    profile = (os.environ.get("AUTOCODE_COST_PROFILE", "default") or "default").strip()
    ladder = " → ".join(["local", *_ladder()])
    return (
        "Cost policy: prefer local; escalate only as heavy as needed.\n"
        f"Profile: {profile}\n"
        f"Ladder: {ladder}\n"
        "Tip: Cursor Ultra includes Grok — set AUTOCODE_COST_PROFILE=cursor-ultra "
        "and leave XAI_API_KEY empty overnight.\n"
        "Overrides: Notion Model route always wins."
    )
