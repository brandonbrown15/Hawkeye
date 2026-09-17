#!/usr/bin/env python3
"""Tests for per-user accounts, connections, projects, and DMs."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import accounts, auth as ui_auth, connections, messages, team_projects  # noqa: E402


class AccountsCollabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-acct-"))
        self._env = {k: os.environ.get(k) for k in (
            "HAWKEYE_ACCOUNTS_DIR",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_MEMORY_KEY",
            "AUTOCODE_PRIVATE_MODE",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["HAWKEYE_ACCOUNTS_DIR"] = str(self.tmp)
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-secrets-key-for-unit-tests"
        os.environ["HAWKEYE_USERS_JSON"] = (
            '{"brandon@brownhawke.engineering":"x","mark@brownhawke.engineering":"y"}'
        )
        ui_auth.clear_users_cache()
        accounts.clear_cache()

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_users_cache()
        accounts.clear_cache()

    def test_profile_per_user(self) -> None:
        a = accounts.update_profile(
            "brandon@brownhawke.engineering",
            first_name="Brandon",
            last_name="Brown",
            employee_number="BH-001",
        )
        b = accounts.get_profile("mark@brownhawke.engineering")
        self.assertTrue(a["profile_complete"])
        self.assertEqual(a["display_name"], "Brandon Brown")
        self.assertFalse(b["profile_complete"])
        directory = accounts.list_directory()
        emails = {u["email"] for u in directory}
        self.assertIn("brandon@brownhawke.engineering", emails)
        self.assertIn("mark@brownhawke.engineering", emails)

    def test_connections_isolated_and_encrypted(self) -> None:
        connections.set_connection(
            "brandon@brownhawke.engineering",
            "github",
            secrets={"token": "ghp_brandon_secret"},
            account_label="brandon-pat",
        )
        connections.set_connection(
            "mark@brownhawke.engineering",
            "github",
            secrets={"token": "ghp_mark_secret"},
        )
        b = connections.list_connections("brandon@brownhawke.engineering")
        m = connections.list_connections("mark@brownhawke.engineering")
        self.assertEqual(b["providers"]["github"]["status"], "connected")
        self.assertEqual(m["providers"]["github"]["status"], "connected")
        self.assertNotIn("ghp_", str(b))
        self.assertEqual(
            connections.get_secret("brandon@brownhawke.engineering", "github", "token"),
            "ghp_brandon_secret",
        )
        self.assertEqual(
            connections.get_secret("mark@brownhawke.engineering", "github", "token"),
            "ghp_mark_secret",
        )
        connections.disconnect("brandon@brownhawke.engineering", "github")
        self.assertEqual(
            connections.list_connections("brandon@brownhawke.engineering")["providers"]["github"]["status"],
            "disconnected",
        )

    def test_project_share_and_dm(self) -> None:
        created = team_projects.create_project(
            "brandon@brownhawke.engineering",
            name="Tunnel cutover",
            description="Public DNS",
        )
        pid = created["project"]["id"]
        team_projects.share_project(
            "brandon@brownhawke.engineering",
            pid,
            member_email="mark@brownhawke.engineering",
            role="editor",
        )
        marks = team_projects.list_projects("mark@brownhawke.engineering")
        self.assertEqual(len(marks["projects"]), 1)
        self.assertEqual(marks["projects"][0]["name"], "Tunnel cutover")

        sent = messages.send_message(
            "brandon@brownhawke.engineering",
            "mark@brownhawke.engineering",
            "Can you review the tunnel PR?",
        )
        self.assertTrue(sent["ok"])
        threads = messages.list_threads("mark@brownhawke.engineering")
        self.assertEqual(threads["unread_total"], 1)
        tid = threads["threads"][0]["thread_id"]
        messages.mark_thread_read("mark@brownhawke.engineering", tid)
        threads2 = messages.list_threads("mark@brownhawke.engineering")
        self.assertEqual(threads2["unread_total"], 0)


if __name__ == "__main__":
    unittest.main()
