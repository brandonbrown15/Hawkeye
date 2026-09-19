"""Hawkeye web research tools."""

from research.web import (
    ResearchResult,
    ResearchSource,
    brave_configured,
    fetch_page_text,
    format_web_policy_for_prompt,
    research,
    wants_deep,
    wants_research,
)

__all__ = [
    "ResearchResult",
    "ResearchSource",
    "brave_configured",
    "fetch_page_text",
    "format_web_policy_for_prompt",
    "research",
    "wants_deep",
    "wants_research",
]
