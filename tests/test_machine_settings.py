"""Tests for machine settings (.env upsert + admin gate)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from ui import auth as ui_auth  # noqa: E402
from ui import machine_settings  # noqa: E402


class MachineSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-mach-"))
        self.env_path = self.tmp / ".env"
        self.env_path.write_text("AUTOCODE_PRODUCT_NAME=Hawkeye\n", encoding="utf-8")
        self._env = {
            k: os.environ.get(k)
            for k in (
                "HAWKEYE_USERS_JSON",
                "HAWKEYE_ADMIN_EMAILS",
                "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
                "HAWKEYE_UPDATE_ENABLED",
                "HAWKEYE_UPDATE_BRANCH",
                "TUNNEL_TOKEN",
                "HAWKEYE_MEMORY_KEY",
            )
        }
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        os.environ["HAWKEYE_USERS_JSON"] = (
            '{"brandon@brownhawke.engineering":"x","mark@brownhawke.engineering":"y"}'
        )
        ui_auth.clear_users_cache()
        self._patchers = [
            mock.patch.object(machine_settings, "ROOT", self.tmp),
            mock.patch.object(machine_settings, "ENV_PATH", self.env_path),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_users_cache()

    def test_default_admin_is_brandon_only(self) -> None:
        self.assertTrue(machine_settings.is_admin("brandon@brownhawke.engineering"))
        self.assertFalse(machine_settings.is_admin("mark@brownhawke.engineering"))
        os.environ["HAWKEYE_ADMIN_EMAILS"] = "mark@brownhawke.engineering"
        self.assertFalse(machine_settings.is_admin("brandon@brownhawke.engineering"))
        self.assertTrue(machine_settings.is_admin("mark@brownhawke.engineering"))

    def test_non_admin_cannot_apply(self) -> None:
        with self.assertRaises(PermissionError):
            machine_settings.apply(
                "mark@brownhawke.engineering",
                {"update_branch": "main"},
            )

    def test_update_branch_defaults_to_main(self) -> None:
        st = machine_settings.update_status()
        self.assertEqual(st["update_branch"], "main")

    def test_apply_writes_tunnel_and_branch(self) -> None:
        out = machine_settings.apply(
            "brandon@brownhawke.engineering",
            {
                "tunnel_token": "eyJtest",
                "update_branch": "cursor/hawkeye-jetson-bootstrap-ef29",
                "update_enabled": "1",
                "memory_key": "unit-test-memory-key",
            },
        )
        text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("TUNNEL_TOKEN=eyJtest", text)
        self.assertIn("HAWKEYE_UPDATE_BRANCH=cursor/hawkeye-jetson-bootstrap-ef29", text)
        self.assertIn("HAWKEYE_MEMORY_KEY=unit-test-memory-key", text)
        self.assertTrue(out["tunnel_token_set"])
        self.assertTrue(out["memory_key_set"])

    def test_memory_key_rotation_requires_force(self) -> None:
        machine_settings.apply(
            "brandon@brownhawke.engineering",
            {"memory_key": "first-key"},
        )
        with self.assertRaises(ValueError):
            machine_settings.apply(
                "brandon@brownhawke.engineering",
                {"memory_key": "second-key"},
            )
        machine_settings.apply(
            "brandon@brownhawke.engineering",
            {"memory_key": "second-key", "force_memory_key": "1"},
        )
        self.assertIn("HAWKEYE_MEMORY_KEY=second-key", self.env_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
