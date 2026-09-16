#!/usr/bin/env python3
"""Mock overnight simulation tests (no network)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.run_night import (  # noqa: E402
    HardwareSnapshot,
    MockNotionSink,
    Task,
    process_task,
    route_task,
)


class OrchestratorMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autocode-test-"))
        os.environ["WORKSPACE_ROOT"] = str(self.tmp / "workspaces")
        self.sink = MockNotionSink(self.tmp / "notion.jsonl")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_local_task_succeeds_in_mock(self) -> None:
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.2, False)
        task = Task(
            page_id="p1",
            task_id="BLD-201",
            name="Tiny docs",
            acceptance="Write a note",
            complexity="Local-safe",
            model_route="Local Hermes",
            repo="app",
            priority="P2",
        )
        digest: list[str] = []
        result = process_task(task, hw, digest, self.sink, mock=True)
        self.assertEqual(result.outcome, "Success")
        kinds = [e["kind"] for e in self.sink.events]
        self.assertIn("claim", kinds)
        self.assertIn("needs_review", kinds)
        self.assertIn("agent_run", kinds)

    def test_cloud_only_escalates_in_mock(self) -> None:
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.2, False)
        task = Task(
            page_id="p2",
            task_id="BLD-202",
            name="Hard auth",
            acceptance="Rebuild auth",
            complexity="Cloud-only",
            model_route="Cursor Cloud",
            repo="app",
            priority="P0",
        )
        digest: list[str] = []
        result = process_task(task, hw, digest, self.sink, mock=True)
        self.assertEqual(result.outcome, "Escalated")
        self.assertEqual(result.escalated_to, "Cursor Cloud")
        kinds = [e["kind"] for e in self.sink.events]
        self.assertIn("escalation", kinds)

    def test_mid_range_cloud_only_goes_grok_bot_in_mock(self) -> None:
        os.environ["AUTOCODE_GROK_DELEGATE_CMD"] = str(
            Path(__file__).resolve().parents[1] / "scripts" / "delegate_grok_stub.sh"
        )
        os.environ["CURSOR_API_KEY"] = "test-cursor"
        os.environ["AUTOCODE_DISABLE_METERED_GROK"] = "1"
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.2, False)
        task = Task(
            page_id="p4",
            task_id="BLD-204",
            name="Handler cleanup",
            acceptance="Tidy one endpoint",
            complexity="Cloud-only",
            model_route="Local Hermes",
            repo="app",
            priority="P2",
        )
        digest: list[str] = []
        result = process_task(task, hw, digest, self.sink, mock=True)
        self.assertEqual(result.outcome, "Escalated")
        self.assertEqual(result.escalated_to, "Grok Bot")

    def test_low_ram_forces_escalate(self) -> None:
        hw = HardwareSnapshot(400, 8000, 40.0, 0.2, True)
        task = Task(
            page_id="p3",
            task_id="BLD-203",
            name="Would be local",
            acceptance="tiny",
            complexity="Local-safe",
            model_route="Local Hermes",
            repo="app",
            priority="P2",
        )
        self.assertNotEqual(route_task(task, hw, 0), "local")


if __name__ == "__main__":
    unittest.main()
