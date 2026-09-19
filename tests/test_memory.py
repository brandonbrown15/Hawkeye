#!/usr/bin/env python3
"""Tests for Hawkeye SSD vector memory."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory import crypto, embed  # noqa: E402
from memory.store import MemoryStore, reset_store_for_tests  # noqa: E402
from ui import identity  # noqa: E402


class EmbedTests(unittest.TestCase):
    def test_hash_embed_normalized_and_stable(self) -> None:
        a = embed.hash_embed("Jetson Hawkeye memory")
        b = embed.hash_embed("Jetson Hawkeye memory")
        self.assertEqual(a, b)
        norm = sum(x * x for x in a) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_cosine_identical(self) -> None:
        v = embed.hash_embed("hello world")
        self.assertGreater(embed.cosine(v, v), 0.99)


class CryptoTests(unittest.TestCase):
    def test_roundtrip_with_key(self) -> None:
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-passphrase-please-rotate"
        try:
            line = crypto.encode_record(
                {
                    "id": "1",
                    "text": "secret turn",
                    "embedding": [0.1],
                    "kind": "chat",
                    "meta": {},
                    "ts": 1.0,
                }
            )
            self.assertTrue(line.startswith("enc:"))
            data = crypto.decode_record(line)
            self.assertEqual(data["text"], "secret turn")
        finally:
            os.environ.pop("HAWKEYE_MEMORY_KEY", None)

    def test_plain_without_key(self) -> None:
        os.environ.pop("HAWKEYE_MEMORY_KEY", None)
        line = crypto.encode_record({"hello": "world"})
        self.assertIn("hello", line)
        self.assertEqual(crypto.decode_record(line)["hello"], "world")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-mem-"))
        os.environ["HAWKEYE_EMBED_FORCE_HASH"] = "1"
        os.environ.pop("HAWKEYE_MEMORY_KEY", None)
        self.store = reset_store_for_tests(self.tmp)

    def tearDown(self) -> None:
        os.environ.pop("HAWKEYE_EMBED_FORCE_HASH", None)
        reset_store_for_tests()

    def test_remember_and_retrieve(self) -> None:
        self.store.remember(
            "Decision: use Cloudflare Tunnel for hawkeye.brownhawke.engineering",
            kind="decision",
        )
        self.store.remember_turn(
            "How do we expose the UI?",
            "Tunnel to 127.0.0.1:8787 with Secure cookies.",
            provider="local",
        )
        hits = self.store.search("Cloudflare Tunnel domain UI", limit=3)
        self.assertTrue(hits)
        self.assertTrue(any("Tunnel" in h.text or "tunnel" in h.text.lower() for h in hits))
        prompt = self.store.format_for_prompt("tunnel domain")
        self.assertIn("Relevant Hawkeye memory", prompt)
        stats = self.store.stats()
        self.assertEqual(stats["count"], 2)
        self.assertFalse(stats["encrypted"])

    def test_encrypted_store(self) -> None:
        os.environ["HAWKEYE_MEMORY_KEY"] = "unit-test-key"
        store = MemoryStore(self.tmp / "enc")
        store.remember("private preference: prefer Cursor over metered Grok", kind="decision")
        raw = store.path.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("enc:"))
        self.assertNotIn("private preference", raw)
        hits = store.search("Cursor preference", limit=2)
        self.assertTrue(hits)
        os.environ.pop("HAWKEYE_MEMORY_KEY", None)

    def test_identity_seed_once(self) -> None:
        first = self.store.ensure_identity_seed(identity.MEMORY_SEED_TEXT)
        second = self.store.ensure_identity_seed(identity.MEMORY_SEED_TEXT)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertTrue(self.store.has_identity_seed())
        hits = self.store.search("Who is Brandon Brown Hawkeye Jetson", limit=3)
        self.assertTrue(any("created Hawkeye" in h.text for h in hits))
        identity.assert_identity_safe(first.text)


if __name__ == "__main__":
    unittest.main()

