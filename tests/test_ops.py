#!/usr/bin/env python3
"""Tests for remote ops control plane."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import ops  # noqa: E402


class OpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autocode-ops-"))
        self._old_status = ops.STATUS_PATH
        self._old_control = ops.CONTROL_PATH
        ops.STATUS_PATH = self.tmp / "status.json"
        ops.CONTROL_PATH = self.tmp / "control.json"

    def tearDown(self) -> None:
        ops.STATUS_PATH = self._old_status
        ops.CONTROL_PATH = self._old_control

    def test_write_and_format_status(self) -> None:
        ops.write_status(phase="running_local", task_id="BLD-1", task_name="x", route="local")
        text = ops.format_status()
        self.assertIn("running_local", text)
        self.assertIn("BLD-1", text)
        self.assertFalse(ops.load_status().looks_stuck(threshold_sec=99999))

    def test_pause_resume_abort_skip(self) -> None:
        ops.set_control(clear=True)
        ops.set_control(paused=True, note="hold")
        self.assertTrue(ops.load_control().paused)
        ops.set_control(paused=False)
        self.assertFalse(ops.load_control().paused)
        ops.set_control(skip_task_id="BLD-9")
        self.assertTrue(ops.should_skip("BLD-9"))
        ops.clear_skip("BLD-9")
        self.assertFalse(ops.should_skip("BLD-9"))
        ops.set_control(abort=True)
        self.assertTrue(ops.load_control().abort)

    def test_stuck_detection(self) -> None:
        ops.write_status(phase="running_local", task_id="BLD-2", detail="working")
        st = ops.load_status()
        # Force old heartbeat
        raw = json.loads(ops.STATUS_PATH.read_text())
        raw["heartbeat_at"] = "2020-01-01T00:00:00+00:00"
        ops.STATUS_PATH.write_text(json.dumps(raw))
        st = ops.load_status()
        self.assertTrue(st.looks_stuck(threshold_sec=60))


if __name__ == "__main__":
    unittest.main()
