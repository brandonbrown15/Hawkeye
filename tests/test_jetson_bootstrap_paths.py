#!/usr/bin/env python3
"""Workspace root resolver prefers writable home over /opt."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ResolveWorkspaceRootTests(unittest.TestCase):
    def test_falls_back_when_opt_unwritable(self) -> None:
        script = ROOT / "scripts" / "resolve_workspace_root.sh"
        env = os.environ.copy()
        env["WORKSPACE_ROOT"] = "/opt/workspaces-that-should-not-exist-ef29"
        env.pop("AUTOCODE_DATA_ROOT", None)
        # Clear repo .env influence by running in a temp copy context via env only —
        # script sources ROOT/.env; override after by forcing HOME.
        with tempfile.TemporaryDirectory() as tmp:
            env["HOME"] = tmp
            out = subprocess.check_output(["bash", str(script)], env=env, text=True).strip()
            self.assertTrue(out.startswith(tmp) or "workspaces" in out, out)
            self.assertNotEqual(out, "/opt/workspaces-that-should-not-exist-ef29")
            self.assertTrue(Path(out).is_dir(), out)

    def test_ensure_ollama_script_exists(self) -> None:
        path = ROOT / "ollama" / "ensure_ollama.sh"
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertIn("ollama serve", text)
        self.assertIn("api/tags", text)
        self.assertIn("--restart", text)

    def test_default_num_ctx_script(self) -> None:
        script = ROOT / "ollama" / "default_num_ctx.sh"
        self.assertTrue(script.is_file())
        out = subprocess.check_output(
            ["bash", str(script)],
            env={**os.environ, "OLLAMA_NUM_CTX": "8192"},
            text=True,
        ).strip()
        self.assertEqual(out, "8192")


if __name__ == "__main__":
    unittest.main()
