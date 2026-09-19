#!/usr/bin/env python3
"""Regression: Brandon is human; Hawkeye (software) runs on the Jetson."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import identity  # noqa: E402


class IdentityPromptTests(unittest.TestCase):
    def test_chat_prompt_separates_brandon_from_jetson(self) -> None:
        prompt = identity.chat_system_prompt("Hawkeye")
        identity.assert_identity_safe(prompt)
        self.assertIn("Hawkeye", prompt)
        self.assertIn("Brandon Brown", prompt)
        self.assertIn("human", prompt.lower())
        self.assertIn("created", prompt.lower())
        self.assertIn("software", prompt.lower())
        self.assertIn("Jetson", prompt)
        self.assertNotIn("You are Brandon", prompt)
        for phrase in identity.FORBIDDEN_IDENTITY_PHRASES:
            self.assertNotIn(phrase, prompt)

    def test_mail_and_cloud_prompts_are_identity_safe(self) -> None:
        mail = identity.mail_system_prompt("Hawkeye")
        cloud = identity.cloud_escalator_prompt("Hawkeye")
        identity.assert_identity_safe(mail)
        identity.assert_identity_safe(cloud)
        self.assertIn("Brandon Brown", mail)
        self.assertIn("human", cloud.lower())

    def test_memory_seed_text(self) -> None:
        identity.assert_identity_safe(identity.MEMORY_SEED_TEXT)
        self.assertIn("Brandon Brown", identity.MEMORY_SEED_TEXT)
        self.assertIn("human", identity.MEMORY_SEED_TEXT.lower())
        self.assertIn("created", identity.MEMORY_SEED_TEXT.lower())
        self.assertIn("Jetson", identity.MEMORY_SEED_TEXT)
        self.assertIn("does not run on a Jetson", identity.MEMORY_SEED_TEXT)

    def test_modelfile_fixture(self) -> None:
        text = (ROOT / "ollama" / "Modelfile.coder-64k").read_text(encoding="utf-8")
        identity.assert_identity_safe(text)
        self.assertIn("Brandon Brown", text)
        self.assertIn("human operator", text)
        self.assertIn("software", text.lower())
        self.assertIn("Jetson", text)
        for phrase in identity.FORBIDDEN_IDENTITY_PHRASES:
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
