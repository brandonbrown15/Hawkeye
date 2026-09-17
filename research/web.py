"""Web research for Hawkeye (stdlib + optional API keys).

Providers (first that works):
  1. Brave Search API if BRAVE_SEARCH_API_KEY is set
  2. DuckDuckGo HTML scrape (no key)

Deep mode (default on): after SERP, fetch top result pages and extract
readable text so the local model can answer from page content, not snippets.
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
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str = ""
    excerpt: str = ""


@dataclass
class ResearchResult:
    query: str
    sources: list[ResearchSource] = field(default_factory=list)
    provider: str = ""
    error: str | None = None
    deep: bool = False
    rounds: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "error": self.error,
            "deep": self.deep,
            "rounds": self.rounds,
            "sources": [asdict(s) for s in self.sources],
        }

    def format_for_prompt(self, *, limit: int = 5) -> str:
        if self.error and not self.sources:
            return f"(web research failed: {self.error})"
        if not self.sources:
            return "(no web sources found)"
        mode = "deep page read" if self.deep else "SERP snippets"
        lines = [
            f"Web research for: {self.query} (via {self.provider}, {mode}, rounds={self.rounds})"
        ]
        for i, src in enumerate(self.sources[:limit], 1):
            snip = (src.snippet or "").replace("\n", " ").strip()
            if len(snip) > 220:
                snip = snip[:217] + "..."
            lines.append(f"{i}. {src.title} — {src.url}")
            if snip:
                lines.append(f"   Snippet: {snip}")
            excerpt = (src.excerpt or "").strip()
            if excerpt:
                if len(excerpt) > 1800:
                    excerpt = excerpt[:1797] + "..."
                lines.append(f"   Page excerpt:\n   {excerpt}")
        lines.append("Cite these URLs when relying on them. Prefer page excerpts over snippets.")
        return "\n".join(lines)

    def format_for_chat(self, *, limit: int = 5) -> str:
        if not self.sources:
            return self.error or "No sources found."
        label = "Deep sources" if self.deep else "Sources"
        lines = [f"{label} ({self.provider}):"]
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
    "deep search",
    "deep research",
    "deep web",
    "thorough research",
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

_DEEP_TRIGGERS = (
    "deep search",
    "deep research",
    "deep web",
    "thorough research",
    "read the docs",
    "read the page",
    "go deep",
)


def wants_research(message: str) -> bool:
    text = (message or "").lower()
    if not text:
        return False
    if os.environ.get("HAWKEYE_RESEARCH_ALWAYS", "").lower() in ("1", "true", "yes"):
        return True
    if any(t in text for t in _RESEARCH_TRIGGERS):
        return True
    if text.startswith("/research ") or text.startswith("research:"):
        return True
    return False


def wants_deep(message: str) -> bool:
    """Deep page-read mode: env default on, or explicit deep triggers."""
    text = (message or "").lower()
    if any(t in text for t in _DEEP_TRIGGERS):
        return True
    return os.environ.get("HAWKEYE_RESEARCH_DEEP", "1").lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def research(query: str, *, limit: int = 5, deep: bool | None = None) -> ResearchResult:
    query = (query or "").strip()
    if query.lower().startswith("research:"):
        query = query.split(":", 1)[1].strip()
    if query.lower().startswith("/research "):
        query = query[10:].strip()
    if not query:
        return ResearchResult(query="", error="empty query")

    do_deep = wants_deep(query) if deep is None else deep
    result = _serp(query, limit=limit)
    if result.error and not result.sources:
        return result

    rounds = 1
    if do_deep and result.sources:
        _enrich_with_pages(result)
        result.deep = True
        # One reformulation pass when pages/snippets are weak.
        if _weak_result(result) and _env_int("HAWKEYE_RESEARCH_MAX_ROUNDS", 2) >= 2:
            alt = _reformulate(query)
            if alt and alt.lower() != query.lower():
                second = _serp(alt, limit=limit)
                if second.sources:
                    _enrich_with_pages(second)
                    # Prefer second-round sources that added excerpts.
                    merged = _merge_sources(result.sources, second.sources, limit=limit)
                    result.sources = merged
                    result.provider = f"{result.provider}+{second.provider}"
                    rounds = 2
        result.rounds = rounds
    else:
        result.deep = False
        result.rounds = 1
    return result


def _serp(query: str, *, limit: int) -> ResearchResult:
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


def _weak_result(result: ResearchResult) -> bool:
    if not result.sources:
        return True
    with_excerpt = sum(1 for s in result.sources if (s.excerpt or "").strip())
    if with_excerpt == 0:
        return True
    total_chars = sum(len(s.excerpt or "") + len(s.snippet or "") for s in result.sources)
    return total_chars < 400


def _reformulate(query: str) -> str:
    q = query.strip()
    # Prefer docs-oriented second pass.
    if "docs" not in q.lower() and "documentation" not in q.lower():
        return f"{q} official documentation"
    return f"{q} site:docs OR site:github.com OR site:readthedocs.io"


def _merge_sources(
    first: list[ResearchSource], second: list[ResearchSource], *, limit: int
) -> list[ResearchSource]:
    seen: set[str] = set()
    out: list[ResearchSource] = []
    for src in list(second) + list(first):
        key = src.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
        if len(out) >= limit:
            break
    return out


def _enrich_with_pages(result: ResearchResult) -> None:
    max_pages = _env_int("HAWKEYE_RESEARCH_FETCH_MAX", 3)
    for src in result.sources[:max_pages]:
        try:
            text = fetch_page_text(src.url)
        except Exception:  # noqa: BLE001
            continue
        if text:
            src.excerpt = text


def fetch_page_text(url: str, *, max_bytes: int | None = None, timeout: int | None = None) -> str:
    """Download a URL and return cleaned visible text (best-effort)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    max_bytes = max_bytes if max_bytes is not None else _env_int("HAWKEYE_RESEARCH_FETCH_BYTES", 200_000)
    timeout = timeout if timeout is not None else _env_int("HAWKEYE_RESEARCH_FETCH_TIMEOUT", 12)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Hawkeye/1.0 (+private research; respect robots)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text/" not in ctype and "xml" not in ctype:
            return ""
        raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    page = raw.decode("utf-8", errors="replace")
    return _html_to_text(page)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0
        self._skip_tags = {"script", "style", "noscript", "svg", "iframe", "header", "footer", "nav"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._skip_tags:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags and self._skip > 0:
            self._skip -= 1
        if tag.lower() in {"p", "div", "li", "br", "h1", "h2", "h3", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def _html_to_text(page: str) -> str:
    # Drop obvious chrome early.
    page = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", page)
    extractor = _TextExtractor()
    try:
        extractor.feed(page)
        extractor.close()
    except Exception:  # noqa: BLE001
        # Fallback: strip tags crudely.
        return html.unescape(re.sub(r"<[^>]+>", " ", page))[:4000].strip()
    text = extractor.text()
    max_chars = _env_int("HAWKEYE_RESEARCH_EXCERPT_CHARS", 4000)
    if len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    return text


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
