"""Tests for Hawkeye self-update script + systemd timer units."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HawkeyeSelfUpdateTests(unittest.TestCase):
    def test_unit_files_exist(self) -> None:
        svc = (ROOT / "cron" / "hawkeye-update.service").read_text()
        timer = (ROOT / "cron" / "hawkeye-update.timer").read_text()
        self.assertIn("hawkeye_self_update.sh", svc)
        self.assertIn("OnUnitActiveSec=5min", timer)
        self.assertIn("hawkeye-update.service", timer)

    def test_script_is_executable_and_help_works(self) -> None:
        script = ROOT / "scripts" / "hawkeye_self_update.sh"
        self.assertTrue(script.is_file())
        out = subprocess.run(
            ["bash", str(script), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("HAWKEYE_UPDATE", out.stdout)

    def test_script_retries_https_with_token(self) -> None:
        text = (ROOT / "scripts" / "hawkeye_self_update.sh").read_text()
        self.assertIn("ensure_https_remote_with_token", text)
        self.assertIn("GITHUB_TOKEN", text)
        self.assertIn("extraheader", text)

    def test_installer_mentions_update_timer(self) -> None:
        text = (ROOT / "scripts" / "install_hawkeye_autostart.sh").read_text()
        self.assertIn("hawkeye-update.timer", text)
        self.assertIn("hawkeye-update.service", text)


if __name__ == "__main__":
    unittest.main()
