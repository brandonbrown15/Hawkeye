"""Unit tests for Cursor Cloud Agents API client."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from integrations import cursor_cloud  # noqa: E402


class CursorCloudTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("CURSOR_") or key.startswith("HAWKEYE_CURSOR"):
                os.environ.pop(key, None)
        os.environ["CURSOR_AGENT_WAIT_SEC"] = "5"
        os.environ["CURSOR_AGENT_POLL_SEC"] = "0"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_normalize_ssh_repo(self) -> None:
        self.assertEqual(
            cursor_cloud._normalize_repo_url("git@github.com:brandonbrown15/Hawkeye.git"),
            "https://github.com/brandonbrown15/Hawkeye",
        )

    def test_create_and_wait(self) -> None:
        create_body = {
            "agent": {
                "id": "bc-test",
                "url": "https://cursor.com/agents/bc-test",
                "latestRunId": "run-1",
            },
            "run": {"id": "run-1", "status": "CREATING"},
        }
        finished = {
            "id": "run-1",
            "status": "FINISHED",
            "result": "Done the thing",
            "git": {"branches": [{"branch": "cursor/x", "prUrl": "https://github.com/o/r/pull/1"}]},
        }
        with mock.patch.object(cursor_cloud, "_request", side_effect=[create_body, finished]) as req:
            out = cursor_cloud.run_prompt("key", "fix tests", wait=True, timeout_sec=5)
        self.assertEqual(out["agent_id"], "bc-test")
        self.assertIn("Done the thing", out["reply"])
        self.assertIn("https://cursor.com/agents/bc-test", out["reply"])
        self.assertIn("PR:", out["reply"])
        self.assertEqual(req.call_args_list[0].args[0], "POST")
        self.assertEqual(req.call_args_list[0].args[1], "/v1/agents")

    def test_escalate_chat_no_repo_uses_plan_mode(self) -> None:
        create_body = {
            "agent": {"id": "bc-q", "url": "https://cursor.com/agents/bc-q", "latestRunId": "run-q"},
            "run": {"id": "run-q", "status": "CREATING"},
        }
        finished = {"id": "run-q", "status": "FINISHED", "result": "plan"}
        with mock.patch.object(cursor_cloud, "_request", side_effect=[create_body, finished]) as req:
            reply = cursor_cloud.escalate_chat("key", "how should we design X?")
        self.assertIn("plan", reply)
        body = req.call_args_list[0].kwargs.get("body") or {}
        self.assertEqual(body.get("mode"), "plan")
        self.assertNotIn("repos", body)

    def test_delegate_from_payload_coding(self) -> None:
        payload = {
            "task": {
                "task_id": "T1",
                "name": "Add healthcheck",
                "repo": "brandonbrown15/Hawkeye",
                "acceptance": "GET /health returns 200",
            },
            "why": "too hard for Jetson",
            "context": "oom",
            "instructions": "open a PR",
        }
        create_body = {
            "agent": {"id": "bc-n", "url": "https://cursor.com/agents/bc-n", "latestRunId": "run-n"},
            "run": {"id": "run-n", "status": "CREATING"},
        }
        with mock.patch.object(cursor_cloud, "_request", return_value=create_body) as req:
            out = cursor_cloud.delegate_from_payload("key", payload)
        self.assertEqual(out["url"], "https://cursor.com/agents/bc-n")
        body = req.call_args.kwargs.get("body") or {}
        self.assertEqual(body["repos"][0]["url"], "https://github.com/brandonbrown15/Hawkeye")
        self.assertTrue(body.get("autoCreatePR"))

    def test_cli_payload(self) -> None:
        payload = {"task": {"task_id": "T", "name": "x", "repo": "", "acceptance": "y"}, "why": "z", "context": ""}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            path = fh.name
        try:
            os.environ["CURSOR_API_KEY"] = "k"
            os.environ["AUTOCODE_DELEGATE_PAYLOAD"] = path
            with mock.patch.object(
                cursor_cloud,
                "delegate_from_payload",
                return_value={"url": "https://cursor.com/agents/bc", "status": "CREATING", "reply": "started"},
            ):
                code = cursor_cloud.main([])
            self.assertEqual(code, 0)
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
