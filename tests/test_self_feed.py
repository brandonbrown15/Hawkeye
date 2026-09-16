#!/usr/bin/env python3
"""Self-feed unit tests (no Notion network)."""

from __future__ import annotations

import unittest

from orchestrator import self_feed


class SelfFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        if self_feed.SEED_LOG.exists():
            self_feed.SEED_LOG.unlink()

    def test_parse_improve_and_bug(self) -> None:
        text = "done\nIMPROVE: add retry backoff\nBUG: null deref in parser\n"
        pairs = self_feed.parse_improve_signals(text)
        self.assertEqual(
            pairs,
            [("improve", "add retry backoff"), ("bug", "null deref in parser")],
        )

    def test_feed_from_agent_output_mock(self) -> None:
        pages = self_feed.feed_from_agent_output(
            "IMPROVE: cache etags\nBUG: fix flaky test\n",
            mock=True,
        )
        self.assertEqual(len(pages), 2)

    def test_routine_health_mock(self) -> None:
        pages = self_feed.maybe_seed_routine_health(mock=True, force=True)
        self.assertTrue(pages)


if __name__ == "__main__":
    unittest.main()
