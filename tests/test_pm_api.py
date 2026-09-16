#!/usr/bin/env python3
"""Tests for Notion-backed Hawkeye PM board helpers / API."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notion import pm as notion_pm  # noqa: E402
from ui import auth as ui_auth  # noqa: E402
from ui import server as ui_server  # noqa: E402


class PmHelpersTests(unittest.TestCase):
    def test_mock_board_summary(self) -> None:
        data = notion_pm.mock_board_summary("hawkeye")
        self.assertGreaterEqual(data["total"], 1)
        self.assertIn("Ready", data["counts"])
        self.assertTrue(data["tasks"][0]["name"])

    def test_list_boards(self) -> None:
        boards = notion_pm.list_boards()
        ids = {b.id for b in boards}
        self.assertIn("hawkeye", ids)
        self.assertIn("rose", ids)


class PmApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-pm-"))
        self._env = {
            k: os.environ.get(k)
            for k in (
                "AUTOCODE_PRIVATE_MODE",
                "AUTOCODE_PRODUCT_NAME",
                "HAWKEYE_PM_MOCK",
                "NOTION_TOKEN",
                "HAWKEYE_USERS_FILE",
            )
        }
        os.environ["AUTOCODE_PRIVATE_MODE"] = "0"
        os.environ["AUTOCODE_PRODUCT_NAME"] = "Hawkeye"
        os.environ["HAWKEYE_PM_MOCK"] = "1"
        os.environ.pop("NOTION_TOKEN", None)
        ui_auth.clear_sessions()
        ui_auth.clear_users_cache()
        ui_server.STATE = self.tmp

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_sessions()

    def test_projects_and_tasks_endpoints(self) -> None:
        httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=5) as resp:
                projects = json.loads(resp.read().decode())
            self.assertTrue(projects["ok"])
            self.assertTrue(projects["boards"])

            with request.urlopen(
                f"http://127.0.0.1:{port}/api/tasks?board=hawkeye&status=all", timeout=5
            ) as resp:
                tasks = json.loads(resp.read().decode())
            self.assertTrue(tasks["ok"])
            self.assertGreaterEqual(tasks["total"], 1)
            page_id = tasks["tasks"][0]["page_id"]

            body = json.dumps({"status": "Done", "token": tasks.get("token") or ui_server.TOKEN}).encode()
            # Need CSRF token from status
            with request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
                snap = json.loads(resp.read().decode())
            tok = snap["token"]
            req = request.Request(
                f"http://127.0.0.1:{port}/api/tasks/{page_id}",
                data=json.dumps({"status": "Done", "token": tok}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Autocode-Token": tok,
                },
                method="POST",
            )
            with request.urlopen(req, timeout=5) as resp:
                updated = json.loads(resp.read().decode())
            self.assertTrue(updated["ok"])
            self.assertEqual(updated["task"]["status"], "Done")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
