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
from research.web import ResearchResult, ResearchSource, _parse_ddg_html, research  # noqa: E402


class WantsResearchTests(unittest.TestCase):
    def test_triggers(self) -> None:
        self.assertTrue(wants_research("research Jetson Ollama CUDA install"))
        self.assertTrue(wants_research("look up the nomic-embed-text docs"))
        self.assertTrue(wants_research("/research cloudflare tunnel dns"))
        self.assertFalse(wants_research("pause the overnight run"))


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
            sources=[
                ResearchSource(
                    title="Ollama embeddings",
                    url="https://example.com/embed",
                    snippet="Use /api/embeddings",
                )
            ],
        )
        text = result.format_for_prompt()
        self.assertIn("https://example.com/embed", text)
        self.assertIn("Cite these URLs", text)

    def test_research_uses_mock_provider(self) -> None:
        fake = ResearchResult(
            query="q",
            provider="brave",
            sources=[ResearchSource(title="t", url="https://x.test", snippet="s")],
        )
        with mock.patch("research.web._brave_search", return_value=fake):
            with mock.patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "x"}, clear=False):
                out = research("research something")
        self.assertEqual(out.provider, "brave")
        self.assertEqual(out.sources[0].url, "https://x.test")


if __name__ == "__main__":
    unittest.main()
