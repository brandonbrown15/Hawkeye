#!/usr/bin/env python3
"""Host / Jetson performance snapshot used by the chat strip."""

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

from ui import auth as ui_auth  # noqa: E402
from ui import host as host_mod  # noqa: E402
from ui import server as ui_server  # noqa: E402


class HostMetricsTests(unittest.TestCase):
    def tearDown(self) -> None:
        host_mod.reset_cpu_sample()

    def test_cpu_pct_from_proc_stat_delta(self) -> None:
        first = "cpu  100 0 100 800 0 0 0 0\n"
        second = "cpu  140 0 140 820 0 0 0 0\n"
        # total +100, idle+iowait +20 → 80% busy
        with mock.patch.object(host_mod, "_read_text", side_effect=[first, second]):
            host_mod.reset_cpu_sample()
            self.assertIsNone(host_mod.cpu_pct())
            self.assertEqual(host_mod.cpu_pct(), 80.0)

    def test_ram_and_jetson_gpu(self) -> None:
        mem = "MemTotal:        8192000 kB\nMemAvailable:    2048000 kB\n"

        def fake_read(path: Path) -> str | None:
            if path.name == "meminfo":
                return mem
            if path.name == "load":
                return "450"
            return None

        with mock.patch.object(host_mod, "_read_text", side_effect=fake_read):
            ram = host_mod.ram_stats()
            gpu, src = host_mod.gpu_pct()
        self.assertEqual(ram["ram_pct"], 75.0)
        self.assertEqual(gpu, 45.0)
        self.assertEqual(src, "jetson")

    def test_snapshot_has_ok_and_no_fake_gpu(self) -> None:
        with mock.patch.object(host_mod, "gpu_pct", return_value=(None, None)):
            with mock.patch.object(host_mod, "temp_c", return_value=None):
                snap = host_mod.snapshot()
        self.assertTrue(snap["ok"])
        self.assertIsNone(snap["gpu_pct"])
        self.assertIn("cpu_pct", snap)
        self.assertIn("load1", snap)


class HostApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-host-"))
        self._env = {k: os.environ.get(k) for k in ("AUTOCODE_PRIVATE_MODE",)}
        os.environ["AUTOCODE_PRIVATE_MODE"] = "0"
        ui_auth.clear_sessions()
        ui_server.STATE = self.tmp

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_sessions()

    def test_api_host_endpoint(self) -> None:
        httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with request.urlopen(f"http://127.0.0.1:{port}/api/host", timeout=5) as resp:
                data = json.loads(resp.read().decode())
            self.assertTrue(data["ok"])
            self.assertIn("cpu_pct", data)
            self.assertIn("gpu_pct", data)
            self.assertIn("load1", data)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
