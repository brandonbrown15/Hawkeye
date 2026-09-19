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

    def test_refuse_secrets_without_encryption_key(self) -> None:
        os.environ.pop("HAWKEYE_MEMORY_KEY", None)
        with self.assertRaises(ValueError) as ctx:
            connections.set_connection(
                "brandon@brownhawke.engineering",
                "github",
                secrets={"token": "ghp_should_fail"},
            )
        self.assertIn("HAWKEYE_MEMORY_KEY", str(ctx.exception))
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-secrets-key-for-unit-tests"

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
        connections.set_request_user("brandon@brownhawke.engineering")
        self.assertEqual(connections.resolve_secret("github", "token"), "ghp_brandon_secret")
        os.environ["GITHUB_TOKEN"] = "ghp_machine_only"
        connections.disconnect("brandon@brownhawke.engineering", "github")
        connections.set_request_user("brandon@brownhawke.engineering")
        self.assertEqual(connections.resolve_secret("github", "token"), "ghp_machine_only")
        self.assertEqual(
            connections.list_connections("brandon@brownhawke.engineering")["providers"]["github"]["status"],
            "machine",
        )
        del os.environ["GITHUB_TOKEN"]
        self.assertEqual(
            connections.list_connections("brandon@brownhawke.engineering")["providers"]["github"]["status"],
            "disconnected",
        )

    def test_notion_token_resolves_from_operator_vault(self) -> None:
        from notion import client as notion_client

        connections.set_connection(
            "brandon@brownhawke.engineering",
            "notion",
            secrets={"token": "ntn_operator_vault"},
        )
        connections.set_request_user(None)
        os.environ.pop("NOTION_TOKEN", None)
        self.assertEqual(notion_client.resolve_notion_token(), "ntn_operator_vault")
        os.environ["NOTION_TOKEN"] = "ntn_machine_env"
        connections.disconnect("brandon@brownhawke.engineering", "notion")
        self.assertEqual(notion_client.resolve_notion_token(), "ntn_machine_env")
        del os.environ["NOTION_TOKEN"]

    def test_connection_placeholders_are_per_field(self) -> None:
        connections.set_connection(
            "brandon@brownhawke.engineering",
            "cursor",
            secrets={"api_key": "key_only_not_webhook"},
        )
        listed = connections.list_connections("brandon@brownhawke.engineering")
        cursor = listed["providers"]["cursor"]
        self.assertEqual(cursor["status"], "connected")
        self.assertEqual(cursor["saved_fields"], ["api_key"])
        self.assertNotIn("webhook_url", cursor["saved_fields"])
        self.assertNotIn("webhook_token", cursor["saved_fields"])
        self.assertEqual(cursor["unreadable_fields"], [])

    def test_unreadable_after_memory_key_rotate(self) -> None:
        connections.set_connection(
            "brandon@brownhawke.engineering",
            "cursor",
            secrets={"api_key": "key_before_rotate"},
        )
        os.environ["HAWKEYE_MEMORY_KEY"] = "rotated-key-that-cannot-decrypt"
        listed = connections.list_connections("brandon@brownhawke.engineering")
        cursor = listed["providers"]["cursor"]
        self.assertEqual(cursor["status"], "unreadable")
        self.assertEqual(cursor["saved_fields"], [])
        self.assertIn("api_key", cursor["unreadable_fields"])
        self.assertEqual(
            connections.unreadable_secret_labels(
                email="brandon@brownhawke.engineering",
                providers=("cursor",),
            ),
            ["cursor.api_key"],
        )
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-secrets-key-for-unit-tests"

    def test_provider_catalog_covers_integrations(self) -> None:
        for pid in (
            "cloudflare",
            "notion",
            "github",
            "cursor",
            "claude",
            "chatgpt",
            "grok",
            "openrouter",
            "brave",
            "telegram",
            "whatsapp",
        ):
            self.assertIn(pid, connections.PROVIDERS)
            self.assertIn(pid, connections.PROVIDER_META)

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
