#!/usr/bin/env python3
"""Tests for Hawkeye web research helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research import wants_research  # noqa: E402
from research.web import (  # noqa: E402
    ResearchResult,
    ResearchSource,
    _parse_ddg_html,
    brave_configured,
    format_web_policy_for_prompt,
    research,
)


class ParseTests(unittest.TestCase):
    def test_parse_ddg_html(self) -> None:
        page = """
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.example.com%2Fguide">
          Example Guide
        </a>
        <a class="result__snippet">Useful engineering notes.</a>
        """
        sources = _parse_ddg_html(page, limit=3)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].url, "https://docs.example.com/guide")
        self.assertIn("Example Guide", sources[0].title)


class ResearchTests(unittest.TestCase):
    def test_format_for_prompt(self) -> None:
        result = ResearchResult(
            query="ollama embeddings",
            provider="duckduckgo",
            deep=True,
            sources=[
                ResearchSource(
                    title="Ollama embeddings",
                    url="https://example.com/embed",
                    snippet="Use /api/embeddings",
                    excerpt="Call POST /api/embeddings with model nomic-embed-text.",
                )
            ],
        )
        text = result.format_for_prompt()
        self.assertIn("https://example.com/embed", text)
        self.assertIn("Page excerpt", text)
        self.assertIn("Cite these URLs", text)

    def test_research_uses_mock_provider(self) -> None:
        fake = ResearchResult(
            query="q",
            provider="brave",
            sources=[ResearchSource(title="t", url="https://x.test", snippet="s")],
        )
        with mock.patch("research.web._brave_search", return_value=fake):
            with mock.patch("research.web._enrich_with_pages"):
                with mock.patch.dict(
                    "os.environ",
                    {"BRAVE_SEARCH_API_KEY": "x", "HAWKEYE_RESEARCH_DEEP": "0"},
                    clear=False,
                ):
                    out = research("research something", deep=False)
        self.assertEqual(out.provider, "brave")
        self.assertEqual(out.sources[0].url, "https://x.test")

    def test_deep_enriches_pages(self) -> None:
        fake = ResearchResult(
            query="cloudflare tunnel",
            provider="brave",
            sources=[
                ResearchSource(title="Tunnel docs", url="https://docs.example.com/tunnel", snippet="short")
            ],
        )
        with mock.patch("research.web._serp", return_value=fake):
            with mock.patch("research.web.fetch_page_text", return_value="Cloudflare Tunnel exposes services without opening ports."):
                with mock.patch.dict("os.environ", {"HAWKEYE_RESEARCH_DEEP": "1", "HAWKEYE_RESEARCH_MAX_ROUNDS": "1"}, clear=False):
                    out = research("deep research cloudflare tunnel", deep=True)
        self.assertTrue(out.deep)
        self.assertIn("exposes services", out.sources[0].excerpt)

    def test_html_to_text(self) -> None:
        from research.web import _html_to_text

        text = _html_to_text("<html><script>bad()</script><body><h1>Hello</h1><p>World</p></body></html>")
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("bad()", text)


class WantsResearchTests(unittest.TestCase):
    def test_triggers(self) -> None:
        self.assertTrue(wants_research("research Jetson Ollama CUDA install"))
        self.assertTrue(wants_research("look up the nomic-embed-text docs"))
        self.assertTrue(wants_research("/research cloudflare tunnel dns"))
        self.assertTrue(wants_research("deep search Cloudflare Tunnel"))
        self.assertTrue(wants_research("search for Cloudflare Tunnel docs"))
        self.assertTrue(wants_research("can you search NVIDIA Jetson news"))
        self.assertFalse(wants_research("pause the overnight run"))
        self.assertFalse(wants_research("mark BLD-1 as Done"))


class BravePolicyTests(unittest.TestCase):
    def test_web_policy_local_only_vs_brave(self) -> None:
        blocked = format_web_policy_for_prompt(local_only=True, brave=True)
        self.assertIn("LOCAL ONLY", blocked)
        self.assertIn("Brave", blocked)
        self.assertIn("turn Local only off", blocked)
        open_brave = format_web_policy_for_prompt(local_only=False, brave=True)
        self.assertIn("Brave Search", open_brave)
        self.assertIn("no internet", open_brave.lower())
        self.assertIn("Never claim", open_brave)

    def test_research_reads_connections_brave_key(self) -> None:
        import os
        import tempfile
        from ui import accounts, connections

        tmp = Path(tempfile.mkdtemp(prefix="hawkeye-brave-"))
        os.environ["HAWKEYE_ACCOUNTS_DIR"] = str(tmp)
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-secrets-key-for-unit-tests"
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        accounts.clear_cache()
        email = "brandon@brownhawke.engineering"
        connections.set_connection(email, "brave", secrets={"api_key": "brave-from-vault"})
        connections.set_request_user(None)
        self.assertTrue(brave_configured(email=email))
        self.assertFalse(brave_configured(email="mark@brownhawke.engineering"))
        fake = ResearchResult(
            query="q",
            provider="brave",
            sources=[ResearchSource(title="t", url="https://x.test", snippet="s")],
        )
        with mock.patch("research.web._brave_search", return_value=fake) as brave:
            with mock.patch.dict("os.environ", {"HAWKEYE_RESEARCH_DEEP": "0"}, clear=False):
                out = research("search for something", deep=False, email=email)
        self.assertEqual(out.provider, "brave")
        brave.assert_called_once()
        self.assertEqual(brave.call_args.kwargs.get("api_key"), "brave-from-vault")


if __name__ == "__main__":
    unittest.main()
