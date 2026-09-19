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
from unittest import mock
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

    def test_normalize_task_id_and_status(self) -> None:
        self.assertEqual(notion_pm.normalize_task_id("hk5"), "HK-5")
        self.assertEqual(notion_pm.normalize_task_id("HK-12"), "HK-12")
        self.assertEqual(notion_pm.normalize_status("done"), "Done")
        self.assertEqual(notion_pm.normalize_status("to Ready please"), None)
        self.assertEqual(notion_pm.normalize_status("Ready please"), "Ready")

    def test_filter_open_priority(self) -> None:
        cards = [
            notion_pm.TaskCard(page_id="1", task_id="HK-1", name="a", status="Done", priority="P0"),
            notion_pm.TaskCard(page_id="2", task_id="HK-2", name="b", status="Ready", priority="P0"),
            notion_pm.TaskCard(page_id="3", task_id="HK-3", name="c", status="Ready", priority="P2"),
        ]
        open_p0 = notion_pm.filter_tasks(cards, open_only=True, priorities=["P0"])
        self.assertEqual([t.task_id for t in open_p0], ["HK-2"])

    def test_create_task_posts_ready_page(self) -> None:
        captured: dict = {}

        def fake_api(method: str, path: str, body=None):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {
                "id": "new-page",
                "url": "https://www.notion.so/new-page",
                "properties": {
                    "Name": {"title": [{"plain_text": "Chat PM slice"}]},
                    "Status": {"select": {"name": "Ready"}},
                    "Priority": {"select": {"name": "P1"}},
                    "Task ID": {"unique_id": {"prefix": "HK", "number": 21}},
                },
            }

        with mock.patch.object(notion_pm, "notion_api", side_effect=fake_api):
            with mock.patch.object(notion_pm, "_token", return_value="tok"):
                card = notion_pm.create_task("Chat PM slice", priority="P1")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/pages")
        self.assertEqual(captured["body"]["properties"]["Status"]["select"]["name"], "Ready")
        self.assertEqual(card.task_id, "HK-21")
        self.assertEqual(card.status, "Ready")

    def test_find_task_by_id_uses_query(self) -> None:
        cards = [
            notion_pm.TaskCard(page_id="p5", task_id="HK-5", name="Orch", status="Ready"),
        ]
        with mock.patch.object(notion_pm, "query_board_tasks", return_value=cards):
            found = notion_pm.find_task_by_id("hk-5")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.page_id, "p5")


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
        notion_pm.clear_mock_tasks()

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

            create = request.Request(
                f"http://127.0.0.1:{port}/api/tasks",
                data=json.dumps({
                    "name": "Queue from API test",
                    "priority": "P1",
                    "status": "Ready",
                    "token": tok,
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Autocode-Token": tok,
                },
                method="POST",
            )
            with request.urlopen(create, timeout=5) as resp:
                created = json.loads(resp.read().decode())
            self.assertTrue(created["ok"])
            self.assertEqual(created["task"]["name"], "Queue from API test")
            self.assertEqual(created["task"]["priority"], "P1")
            self.assertTrue(created["task"]["task_id"])

            with request.urlopen(
                f"http://127.0.0.1:{port}/api/tasks?board=hawkeye&status=all", timeout=5
            ) as resp:
                after = json.loads(resp.read().decode())
            names = [t["name"] for t in after["tasks"]]
            self.assertIn("Queue from API test", names)
        finally:
            httpd.shutdown()
            httpd.server_close()
            notion_pm.clear_mock_tasks()


if __name__ == "__main__":
    unittest.main()
