"""Hawkeye web research tools."""

from research.web import (
    ResearchResult,
    ResearchSource,
    asks_web_access,
    brave_configured,
    claims_no_web_access,
    fetch_page_text,
    format_web_policy_for_prompt,
    research,
    scrub_no_web_claims,
    should_research,
    wants_deep,
    wants_deep_explicit,
    wants_research,
)

__all__ = [
    "ResearchResult",
    "ResearchSource",
    "asks_web_access",
    "brave_configured",
    "claims_no_web_access",
    "fetch_page_text",
    "format_web_policy_for_prompt",
    "research",
    "scrub_no_web_claims",
    "should_research",
    "wants_deep",
    "wants_deep_explicit",
    "wants_research",
]
