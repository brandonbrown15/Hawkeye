"""Tests for Hawkeye boot auto-start unit templates + installer rewrite."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HawkeyeAutostartTests(unittest.TestCase):
    def test_unit_files_exist_and_brand_hawkeye(self) -> None:
        ui = (ROOT / "cron" / "hawkeye-ui.service").read_text()
        tunnel = (ROOT / "cron" / "hawkeye-tunnel.service").read_text()
        update = (ROOT / "cron" / "hawkeye-update.service").read_text()
        timer = (ROOT / "cron" / "hawkeye-update.timer").read_text()
        self.assertIn("Hawkeye", ui)
        self.assertIn("scripts/ui.sh", ui)
        self.assertIn("Restart=always", ui)
        self.assertIn("cloudflared", tunnel)
        self.assertIn("hawkeye-ui.service", tunnel)
        self.assertIn("hawkeye_self_update.sh", update)
        self.assertIn("OnUnitActiveSec=5min", timer)

    def test_installer_rewrites_paths_into_tmpdir(self) -> None:
        script = ROOT / "scripts" / "install_hawkeye_autostart.sh"
        self.assertTrue(script.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp) / "units"
            unit_dir.mkdir()
            # Dry rewrite only (same Python block as installer).
            env = {
                **os.environ,
                "ROOT": str(ROOT),
                "MODE": "user",
                "UNIT_USER": "tester",
                "UNIT_GROUP": "tester",
                "SRC": str(ROOT / "cron" / "hawkeye-ui.service"),
                "DEST": str(unit_dir / "hawkeye-ui.service"),
            }
            subprocess.run(
                [
                    "python3",
                    "-c",
                    """
import os
from pathlib import Path
src = Path(os.environ["SRC"])
dest = Path(os.environ["DEST"])
root = os.environ["ROOT"]
text = src.read_text().replace("/opt/autocode", root)
dest.write_text(text)
""",
                ],
                check=True,
                env=env,
            )
            out = (unit_dir / "hawkeye-ui.service").read_text()
            self.assertIn(str(ROOT), out)
            self.assertNotIn("/opt/autocode", out)


if __name__ == "__main__":
    unittest.main()
