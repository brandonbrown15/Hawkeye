"""Tests for Hawkeye self-update script + systemd timer units."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


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
        self.assertIn("--reset", out.stdout)

    def test_installer_mentions_update_timer(self) -> None:
        text = (ROOT / "scripts" / "install_hawkeye_autostart.sh").read_text()
        self.assertIn("hawkeye-update.timer", text)
        self.assertIn("hawkeye-update.service", text)

    def test_reset_discards_dirty_and_fast_forwards(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="hawkeye-upd-"))
        origin = tmp / "origin.git"
        work = tmp / "work"
        subprocess.check_call(["git", "init", "--bare", str(origin)])
        subprocess.check_call(["git", "clone", str(origin), str(work)])
        _git(work, "config", "user.email", "test@example.com")
        _git(work, "config", "user.name", "Test")
        (work / "README").write_text("v1\n", encoding="utf-8")
        (work / ".env").write_text("TUNNEL_TOKEN=keep-me\n", encoding="utf-8")
        (work / ".gitignore").write_text(".env\nlogs/\nstate/\n", encoding="utf-8")
        scripts = work / "scripts"
        scripts.mkdir()
        shutil.copy2(ROOT / "scripts" / "hawkeye_self_update.sh", scripts / "hawkeye_self_update.sh")
        _git(work, "add", "README", ".gitignore", "scripts/hawkeye_self_update.sh")
        _git(work, "commit", "-m", "v1")
        _git(work, "branch", "-M", "main")
        _git(work, "push", "-u", "origin", "main")
        old = _git(work, "rev-parse", "HEAD")

        (work / "README").write_text("v2\n", encoding="utf-8")
        _git(work, "add", "README")
        _git(work, "commit", "-m", "v2")
        _git(work, "push", "origin", "main")
        new = _git(work, "rev-parse", "HEAD")
        _git(work, "reset", "--hard", old)
        (work / "README").write_text("local dirty hotfix\n", encoding="utf-8")
        self.assertTrue((work / ".env").is_file())

        check = subprocess.run(
            ["bash", str(scripts / "hawkeye_self_update.sh"), "--check"],
            cwd=str(work),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("working-tree=dirty", check.stdout)

        reset = subprocess.run(
            ["bash", str(scripts / "hawkeye_self_update.sh"), "--reset"],
            cwd=str(work),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(reset.returncode, 0, reset.stdout + reset.stderr)
        self.assertEqual(_git(work, "rev-parse", "HEAD"), new)
        self.assertEqual((work / "README").read_text(encoding="utf-8"), "v2\n")
        self.assertEqual((work / ".env").read_text(encoding="utf-8"), "TUNNEL_TOKEN=keep-me\n")
        self.assertEqual(_git(work, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
