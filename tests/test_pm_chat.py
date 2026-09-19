#!/usr/bin/env python3
"""Unit tests for Hawkeye chat PM intents (mocked Notion)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notion import pm as notion_pm  # noqa: E402
from ui import pm_chat  # noqa: E402
from ui import server as ui_server  # noqa: E402


def _card(**kwargs: object) -> notion_pm.TaskCard:
    base = dict(
        page_id="page-hk-5",
        task_id="HK-5",
        name="Unified orchestrator",
        status="Ready",
        priority="P1",
        board_id="hawkeye",
    )
    base.update(kwargs)
    return notion_pm.TaskCard(**base)  # type: ignore[arg-type]


class ParsePmIntentTests(unittest.TestCase):
    def test_list_hawkeye_board(self) -> None:
        intent = pm_chat.parse_pm_intent("what's on the Hawkeye board?")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.action, "list")
        self.assertEqual(intent.board_id, "hawkeye")
        self.assertTrue(intent.open_only)

    def test_list_plain_board(self) -> None:
        intent = pm_chat.parse_pm_intent("what's on the board")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.action, "list")
        self.assertEqual(intent.board_id, "hawkeye")

    def test_show_open_p0_p1(self) -> None:
        intent = pm_chat.parse_pm_intent("show open P0/P1")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.action, "list")
        self.assertEqual(intent.priorities, ["P0", "P1"])
        self.assertTrue(intent.open_only)

    def test_show_open_p0(self) -> None:
        intent = pm_chat.parse_pm_intent("show open P0")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.priorities, ["P0"])

    def test_mark_done(self) -> None:
        intent = pm_chat.parse_pm_intent("mark HK-12 Done")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.action, "update")
        self.assertEqual(intent.task_id, "HK-12")
        self.assertEqual(intent.status, "Done")

    def test_set_ready_lowercase(self) -> None:
        intent = pm_chat.parse_pm_intent("set hk5 to Ready")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.task_id, "HK-5")
        self.assertEqual(intent.status, "Ready")

    def test_add_ready_task(self) -> None:
        intent = pm_chat.parse_pm_intent("add a Ready task: wire PM chat commands")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.action, "create")
        self.assertEqual(intent.title, "wire PM chat commands")
        self.assertEqual(intent.status, "Ready")
        self.assertEqual(intent.priority, "P2")

    def test_add_p1_ready_task(self) -> None:
        intent = pm_chat.parse_pm_intent("add a P1 Ready task: fix login")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.priority, "P1")
        self.assertEqual(intent.title, "fix login")

    def test_rose_board(self) -> None:
        intent = pm_chat.parse_pm_intent("show the ROSE board")
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.board_id, "rose")

    def test_non_pm_falls_through(self) -> None:
        for msg in (
            "redesign the multi-service architecture",
            "Can you review the GitHub repo Hawkeye please",
            "hard thing",
            "research Cloudflare Tunnel",
            "add to checklist later after we research",
            "mark this done",
            "what's on your mind",
        ):
            self.assertIsNone(pm_chat.parse_pm_intent(msg), msg)


class ExecutePmIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {
            k: os.environ.get(k)
            for k in ("HAWKEYE_PM_MOCK", "HAWKEYE_MEMORY_ENABLED", "HAWKEYE_EMBED_FORCE_HASH")
        }
        os.environ.pop("HAWKEYE_PM_MOCK", None)
        os.environ["HAWKEYE_MEMORY_ENABLED"] = "1"
        os.environ["HAWKEYE_EMBED_FORCE_HASH"] = "1"
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-pm-chat-"))
        from memory.store import reset_store_for_tests

        self.store = reset_store_for_tests(self.tmp)

    def tearDown(self) -> None:
        from memory.store import reset_store_for_tests

        reset_store_for_tests()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_list_filters_open_p0_p1(self) -> None:
        cards = [
            _card(task_id="HK-2", name="Deploy", status="Ready", priority="P0"),
            _card(task_id="HK-5", name="Orchestrator", status="Ready", priority="P1"),
            _card(task_id="HK-6", name="PM expand", status="Ready", priority="P2"),
            _card(task_id="HK-1", name="Grant access", status="Done", priority="P0"),
        ]
        with mock.patch.object(notion_pm, "query_board_tasks", return_value=cards):
            out = pm_chat.execute_pm_intent(
                pm_chat.PmIntent(action="list", board_id="hawkeye", priorities=["P0", "P1"], open_only=True)
            )
        self.assertTrue(out["ok"])
        ids = {t["task_id"] for t in out["tasks"]}
        self.assertEqual(ids, {"HK-2", "HK-5"})
        self.assertIn("HK-2", out["reply"])
        self.assertNotIn("HK-6", out["reply"])
        self.assertNotIn("HK-1", out["reply"])
        self.assertTrue(out["decision_id"])
        records = self.store.load()
        self.assertTrue(any(r.kind == "decision" and "P0/P1" in r.text for r in records))

    def test_update_calls_notion(self) -> None:
        found = _card(page_id="page-12", task_id="HK-12", name="Login", status="Ready")
        updated = _card(page_id="page-12", task_id="HK-12", name="Login", status="Done")
        with mock.patch.object(notion_pm, "find_task_by_id", return_value=found) as find:
            with mock.patch.object(notion_pm, "update_task_status", return_value=updated) as upd:
                out = pm_chat.execute_pm_intent(
                    pm_chat.PmIntent(action="update", task_id="HK-12", status="Done")
                )
        find.assert_called_once_with("HK-12", "hawkeye")
        upd.assert_called_once_with("page-12", "Done")
        self.assertTrue(out["ok"])
        self.assertIn("Set HK-12 to Done", out["reply"])
        self.assertTrue(out["decision_id"])

    def test_update_missing_task(self) -> None:
        with mock.patch.object(notion_pm, "find_task_by_id", return_value=None):
            out = pm_chat.execute_pm_intent(
                pm_chat.PmIntent(action="update", task_id="HK-99", status="Done")
            )
        self.assertFalse(out["ok"])
        self.assertIn("Could not find HK-99", out["reply"])

    def test_create_calls_notion(self) -> None:
        created = _card(
            page_id="page-new",
            task_id="HK-20",
            name="wire PM chat commands",
            status="Ready",
            priority="P2",
        )
        with mock.patch.object(notion_pm, "create_task", return_value=created) as create:
            out = pm_chat.execute_pm_intent(
                pm_chat.PmIntent(action="create", title="wire PM chat commands", status="Ready", priority="P2")
            )
        create.assert_called_once()
        self.assertEqual(create.call_args[0][0], "wire PM chat commands")
        self.assertTrue(out["ok"])
        self.assertEqual(out["seeded_task"], "page-new")
        self.assertIn("HK-20", out["reply"])

    def test_notion_error_is_reply(self) -> None:
        with mock.patch.object(
            notion_pm,
            "query_board_tasks",
            side_effect=notion_pm.NotionError("token missing", status=503),
        ):
            out = pm_chat.execute_pm_intent(pm_chat.PmIntent(action="list"))
        self.assertFalse(out["ok"])
        self.assertIn("Notion PM failed", out["reply"])


class HandleChatPmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-pm-ui-"))
        self._env = {
            k: os.environ.get(k)
            for k in (
                "AUTOCODE_PERSONAL_LOCAL_ONLY",
                "CURSOR_API_KEY",
                "CURSOR_WEBHOOK_URL",
                "HAWKEYE_MEMORY_ENABLED",
                "HAWKEYE_PM_MOCK",
            )
        }
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        os.environ.pop("CURSOR_WEBHOOK_URL", None)
        os.environ["HAWKEYE_MEMORY_ENABLED"] = "0"
        os.environ.pop("HAWKEYE_PM_MOCK", None)
        ui_server.STATE = self.tmp

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_board_question_skips_ollama_and_cursor(self) -> None:
        pm_out = {
            "ok": True,
            "action": "list",
            "reply": "Hawkeye board — 1 open:\n- HK-5 [P1 Ready] Orchestrator",
            "tasks": [],
            "seeded_task": None,
        }
        with mock.patch.object(ui_server, "_ollama_chat") as ollama:
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                with mock.patch("ui.pm_chat.execute_pm_intent", return_value=pm_out):
                    out = ui_server.handle_chat("what's on the Hawkeye board?", seed_notion=False)
        ollama.assert_not_called()
        cloud.assert_not_called()
        self.assertFalse(out["escalated"])
        self.assertEqual(out["provider"], "pm")
        self.assertIn("HK-5", out["local_reply"])

    def test_escalate_still_reaches_cursor(self) -> None:
        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: too hard"):
            with mock.patch(
                "integrations.cursor_cloud.escalate_chat",
                return_value="Cloud agent: https://cursor.com/agents/bc-pm",
            ) as api:
                out = ui_server.handle_chat(
                    "redesign the multi-service architecture",
                    seed_notion=False,
                )
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        api.assert_called_once()


if __name__ == "__main__":
    unittest.main()
