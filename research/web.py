"""Lightweight web research for Hawkeye (stdlib + optional API keys).

Providers (first that works):
  1. Brave Search API if BRAVE_SEARCH_API_KEY is set
  2. DuckDuckGo HTML scrape (no key)
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str = ""


@dataclass
class ResearchResult:
    query: str
    sources: list[ResearchSource] = field(default_factory=list)
    provider: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "error": self.error,
            "sources": [asdict(s) for s in self.sources],
        }

    def format_for_prompt(self, *, limit: int = 5) -> str:
        if self.error and not self.sources:
            return f"(web research failed: {self.error})"
        if not self.sources:
            return "(no web sources found)"
        lines = [f"Web research for: {self.query} (via {self.provider})"]
        for i, src in enumerate(self.sources[:limit], 1):
            snip = (src.snippet or "").replace("\n", " ").strip()
            if len(snip) > 220:
                snip = snip[:217] + "..."
            lines.append(f"{i}. {src.title} — {src.url}")
            if snip:
                lines.append(f"   {snip}")
        lines.append("Cite these URLs when relying on them.")
        return "\n".join(lines)

    def format_for_chat(self, *, limit: int = 5) -> str:
        if not self.sources:
            return self.error or "No sources found."
        lines = [f"Sources ({self.provider}):"]
        for i, src in enumerate(self.sources[:limit], 1):
            lines.append(f"{i}. [{src.title}]({src.url})")
            if src.snippet:
                lines.append(f"   {src.snippet.strip()[:200]}")
        return "\n".join(lines)


_RESEARCH_TRIGGERS = (
    "research",
    "look up",
    "search the web",
    "search online",
    "google",
    "what does the docs say",
    "latest",
    "current price",
    "compare options",
    "find documentation",
    "find docs",
    "browse",
    "who makes",
    "datasheet",
)


def wants_research(message: str) -> bool:
    text = (message or "").lower()
    if not text:
        return False
    if os.environ.get("HAWKEYE_RESEARCH_ALWAYS", "").lower() in ("1", "true", "yes"):
        return True
    if any(t in text for t in _RESEARCH_TRIGGERS):
        return True
    # Explicit slash-style
    if text.startswith("/research ") or text.startswith("research:"):
        return True
    return False


def research(query: str, *, limit: int = 5) -> ResearchResult:
    query = (query or "").strip()
    if query.lower().startswith("research:"):
        query = query.split(":", 1)[1].strip()
    if query.lower().startswith("/research "):
        query = query[10:].strip()
    if not query:
        return ResearchResult(query="", error="empty query")

    if os.environ.get("BRAVE_SEARCH_API_KEY", "").strip():
        try:
            return _brave_search(query, limit=limit)
        except Exception as e:  # noqa: BLE001
            brave_err = str(e)
    else:
        brave_err = None

    try:
        return _duckduckgo_html(query, limit=limit)
    except Exception as e:  # noqa: BLE001
        err = str(e)
        if brave_err:
            err = f"brave: {brave_err}; ddg: {err}"
        return ResearchResult(query=query, error=err)


def _brave_search(query: str, *, limit: int) -> ResearchResult:
    key = os.environ["BRAVE_SEARCH_API_KEY"].strip()
    params = urllib.parse.urlencode({"q": query, "count": max(1, min(limit, 10))})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
            "User-Agent": "Hawkeye/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    results = ((data.get("web") or {}).get("results")) or []
    sources: list[ResearchSource] = []
    for item in results[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or url).strip()
        snippet = str(item.get("description") or "").strip()
        if url:
            sources.append(ResearchSource(title=title or url, url=url, snippet=snippet))
    return ResearchResult(query=query, sources=sources, provider="brave")


def _duckduckgo_html(query: str, *, limit: int) -> ResearchResult:
    params = urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{params}",
        headers={
            "User-Agent": "Hawkeye/1.0 (+private research; respect robots)",
            "Accept": "text/html",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    sources = _parse_ddg_html(page, limit=limit)
    return ResearchResult(query=query, sources=sources, provider="duckduckgo")


_RESULT_RE = re.compile(
    r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(?P<snip>.*?)</(?:a|td|div)',
    re.IGNORECASE | re.DOTALL,
)


def _parse_ddg_html(page: str, *, limit: int) -> list[ResearchSource]:
    sources: list[ResearchSource] = []
    snippets = [html.unescape(re.sub(r"<[^>]+>", "", m.group("snip"))).strip() for m in _SNIPPET_RE.finditer(page)]
    for i, m in enumerate(_RESULT_RE.finditer(page)):
        if len(sources) >= limit:
            break
        href = html.unescape(m.group("href"))
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group("title"))).strip()
        url = _unwrap_ddg_url(href)
        if not url:
            continue
        snip = snippets[i] if i < len(snippets) else ""
        sources.append(ResearchSource(title=title or url, url=url, snippet=snip))
    return sources


def _unwrap_ddg_url(href: str) -> str:
    """DuckDuckGo wraps outbound links as /l/?uddg=<url>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return urllib.parse.unquote(qs["uddg"][0])
    if parsed.scheme in ("http", "https"):
        return href
    return ""
