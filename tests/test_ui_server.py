#!/usr/bin/env python3
"""Tests for Autocode / Hawkeye local UI server helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import ops  # noqa: E402
from ui import auth as ui_auth  # noqa: E402
from ui import runtime_settings as runtime  # noqa: E402
from ui import server as ui_server  # noqa: E402


class UiHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autocode-ui-"))
        self._old_status = ops.STATUS_PATH
        self._old_control = ops.CONTROL_PATH
        self._old_demo = ui_server._demo_log
        self._env = {k: os.environ.get(k) for k in (
            "AUTOCODE_PRIVATE_MODE",
            "AUTOCODE_PRIVATE_USER",
            "AUTOCODE_PRIVATE_PASSWORD_HASH",
            "AUTOCODE_PERSONAL_LOCAL_ONLY",
            "AUTOCODE_LOCAL_ONLY",
            "AUTOCODE_PRODUCT_NAME",
            "CURSOR_WEBHOOK_URL",
            "GROK_BOT_WEBHOOK_URL",
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_RUNTIME_FILE",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["AUTOCODE_PRODUCT_NAME"] = "Hawkeye"
        os.environ["AUTOCODE_PRIVATE_MODE"] = "0"
        os.environ["HAWKEYE_RUNTIME_FILE"] = str(self.tmp / "hawkeye-runtime.json")
        runtime.clear_cache()
        ui_auth.clear_sessions()
        ui_auth.clear_users_cache()
        ops.STATUS_PATH = self.tmp / "status.json"
        ops.CONTROL_PATH = self.tmp / "control.json"
        ui_server._demo_log = self.tmp / "ui-demo.log"
        ui_server.STATE = self.tmp

    def tearDown(self) -> None:
        ops.STATUS_PATH = self._old_status
        ops.CONTROL_PATH = self._old_control
        ui_server._demo_log = self._old_demo
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        runtime.clear_cache()
        ui_auth.clear_sessions()
        ui_auth.clear_users_cache()
    def test_snapshot_and_control(self) -> None:
        ops.write_status(phase="running_local", task_id="BLD-1", task_name="docs", route="local")
        snap = ui_server.snapshot()
        self.assertEqual(snap["status"]["phase"], "running_local")
        self.assertIn("token", snap)

        out = ui_server.apply_control("pause", note="ui test")
        self.assertTrue(out["ok"])
        self.assertTrue(ops.load_control().paused)

        out = ui_server.apply_control("resume")
        self.assertTrue(out["ok"])
        self.assertFalse(ops.load_control().paused)

        out = ui_server.apply_control("skip", task_id="BLD-9")
        self.assertTrue(out["ok"])
        self.assertEqual(ops.load_control().skip_task_id, "BLD-9")

        out = ui_server.apply_control("skip")
        self.assertFalse(out["ok"])

    def test_readiness_shape(self) -> None:
        with mock.patch.object(ui_server.health_mod, "check_local_stack") as chk:
            chk.return_value = mock.Mock(
                hermes_ok=True,
                ollama_ok=True,
                ollama_model="coder-64k",
                details=["hermes: present", "ollama: ok"],
            )
            data = ui_server.readiness()
        self.assertIn("checks", data)
        self.assertIn("ready", data)
        self.assertEqual(data["product"], "Hawkeye")
        ids = {c["id"] for c in data["checks"]}
        self.assertIn("hermes", ids)
        self.assertIn("notion", ids)

    def test_http_status_and_control(self) -> None:
        ops.write_status(phase="idle", detail="test")
        httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
                snap = json.loads(resp.read().decode())
            self.assertEqual(snap["status"]["phase"], "idle")
            token = snap["token"]

            body = json.dumps({"action": "pause", "note": "http", "token": token}).encode()
            req = request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Autocode-Token": token,
                },
                method="POST",
            )
            with request.urlopen(req, timeout=5) as resp:
                out = json.loads(resp.read().decode())
            self.assertTrue(out["ok"])
            self.assertTrue(ops.load_control().paused)

            bad = request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=json.dumps({"action": "resume", "token": "nope"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(bad, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

            with request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
                html = resp.read().decode()
            self.assertIn("Hawkeye", html)
            self.assertIn(token, html)
            self.assertIn("localOnlyToggle", html)
            self.assertIn("Local only", html)

            with request.urlopen(f"http://127.0.0.1:{port}/api/settings", timeout=5) as resp:
                settings = json.loads(resp.read().decode())
            self.assertTrue(settings["ok"])
            self.assertFalse(settings["personal_local_only"])

            body = json.dumps({"personal_local_only": True, "token": token}).encode()
            req = request.Request(
                f"http://127.0.0.1:{port}/api/settings",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Autocode-Token": token,
                },
                method="POST",
            )
            with request.urlopen(req, timeout=5) as resp:
                toggled = json.loads(resp.read().decode())
            self.assertTrue(toggled["ok"])
            self.assertTrue(toggled["personal_local_only"])
            self.assertEqual(toggled.get("user"), runtime.OPEN_USER)
            self.assertTrue(ui_auth.personal_local_only(runtime.OPEN_USER))
            self.assertFalse(ui_auth.personal_local_only("mark@brownhawke.engineering"))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_password_hash_roundtrip(self) -> None:
        stored = ui_auth.hash_password("correct-horse")
        self.assertTrue(ui_auth.verify_password("correct-horse", stored))
        self.assertFalse(ui_auth.verify_password("wrong", stored))

    def test_private_login_gate(self) -> None:
        os.environ["AUTOCODE_PRIVATE_MODE"] = "1"
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        users_path = self.tmp / "users.json"
        users_path.write_text(
            json.dumps(
                {
                    "allowed_domain": "brownhawke.engineering",
                    "users": {
                        "brandon@brownhawke.engineering": ui_auth.hash_password("secret-pass"),
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["HAWKEYE_USERS_FILE"] = str(users_path)
        os.environ.pop("AUTOCODE_PRIVATE_USER", None)
        os.environ.pop("AUTOCODE_PRIVATE_PASSWORD_HASH", None)
        ui_auth.clear_users_cache()
        ui_auth.clear_sessions()

        httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5)
            self.assertEqual(ctx.exception.code, 401)

            with request.urlopen(f"http://127.0.0.1:{port}/login", timeout=5) as resp:
                login_html = resp.read().decode()
            self.assertIn("Hawkeye", login_html)
            self.assertIn("brownhawke.engineering", login_html)

            # Outside domain rejected
            outside = request.Request(
                f"http://127.0.0.1:{port}/api/login",
                data=json.dumps(
                    {"email": "brandon@gmail.com", "password": "secret-pass"}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(outside, timeout=5)
            self.assertEqual(ctx.exception.code, 401)

            bad = request.Request(
                f"http://127.0.0.1:{port}/api/login",
                data=json.dumps(
                    {"email": "brandon@brownhawke.engineering", "password": "nope"}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(bad, timeout=5)
            self.assertEqual(ctx.exception.code, 401)

            good = request.Request(
                f"http://127.0.0.1:{port}/api/login",
                data=json.dumps(
                    {
                        "email": "Brandon@brownhawke.engineering",
                        "password": "secret-pass",
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(good, timeout=5) as resp:
                out = json.loads(resp.read().decode())
                cookie = resp.headers.get("Set-Cookie", "")
            self.assertTrue(out["ok"])
            self.assertIn("hawkeye_session=", cookie)

            status_req = request.Request(
                f"http://127.0.0.1:{port}/api/status",
                headers={"Cookie": cookie.split(";", 1)[0]},
            )
            with request.urlopen(status_req, timeout=5) as resp:
                snap = json.loads(resp.read().decode())
            self.assertIn("token", snap)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_work_email_domain_and_users_file(self) -> None:
        path = ROOT / "config" / "users.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        digest = data["users"]["brandon@brownhawke.engineering"]
        self.assertTrue(digest.startswith("pbkdf2_sha256$"))
        self.assertTrue(ui_auth.is_allowed_email("brandon@brownhawke.engineering"))
        self.assertTrue(ui_auth.is_allowed_email("Brandon@BrownHawke.engineering"))
        self.assertFalse(ui_auth.is_allowed_email("brandon@gmail.com"))
        os.environ["HAWKEYE_USERS_FILE"] = str(path)
        os.environ.pop("AUTOCODE_PRIVATE_USER", None)
        os.environ.pop("AUTOCODE_PRIVATE_PASSWORD_HASH", None)
        ui_auth.clear_users_cache()
        users = ui_auth.load_users(reload=True)
        self.assertIn("brandon@brownhawke.engineering", users)

    def test_chat_escalates_to_cursor_webhook(self) -> None:
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"

        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: too hard"):
            with mock.patch.object(ui_server, "_webhook_chat", return_value="premium plan") as wh:
                out = ui_server.handle_chat("redesign the multi-service architecture", seed_notion=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        self.assertEqual(out["cloud_reply"], "premium plan")
        wh.assert_called_once()

    def test_chat_local_only_skips_cloud(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "1"
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: nope"):
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                out = ui_server.handle_chat("hard thing", seed_notion=False)
        cloud.assert_not_called()
        self.assertFalse(out["escalated"])
        self.assertTrue(out["local_only"])

    def test_runtime_local_only_toggle_overrides_env(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        brandon = "brandon@brownhawke.engineering"
        mark = "mark@brownhawke.engineering"
        self.assertFalse(ui_auth.personal_local_only(brandon))

        out = runtime.set_personal_local_only(True, user=brandon)
        self.assertTrue(out["personal_local_only"])
        self.assertEqual(out["user"], brandon)
        self.assertEqual(out["source"], "user")
        self.assertTrue(ui_auth.personal_local_only(brandon))
        self.assertFalse(ui_auth.personal_local_only(mark))
        self.assertTrue((self.tmp / "hawkeye-runtime.json").is_file())

        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: nope"):
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                chat = ui_server.handle_chat("hard thing", seed_notion=False, user=brandon)
        cloud.assert_not_called()
        self.assertTrue(chat["local_only"])

        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: nope"):
            with mock.patch.object(ui_server, "_webhook_chat", return_value="premium") as wh:
                mark_chat = ui_server.handle_chat("hard thing", seed_notion=False, user=mark)
        wh.assert_called_once()
        self.assertTrue(mark_chat["escalated"])

        runtime.set_personal_local_only(False, user=brandon)
        self.assertFalse(ui_auth.personal_local_only(brandon))
        ready = ui_server.readiness(user=brandon)
        self.assertFalse(ready["personal_local_only"])

    def test_per_user_local_only_independent(self) -> None:
        brandon = "brandon@brownhawke.engineering"
        mark = "mark@brownhawke.engineering"
        runtime.set_personal_local_only(True, user=brandon)
        runtime.set_personal_local_only(False, user=mark)
        self.assertTrue(runtime.personal_local_only(brandon))
        self.assertFalse(runtime.personal_local_only(mark))
        runtime.set_personal_local_only(True, user=mark)
        self.assertTrue(runtime.personal_local_only(brandon))
        self.assertTrue(runtime.personal_local_only(mark))

    def test_chat_uses_memory_and_research(self) -> None:
        mem_root = self.tmp / "mem"
        os.environ["HAWKEYE_EMBED_FORCE_HASH"] = "1"
        os.environ["HAWKEYE_MEMORY_ENABLED"] = "1"
        os.environ["HAWKEYE_RESEARCH_ENABLED"] = "1"
        from memory.store import reset_store_for_tests

        store = reset_store_for_tests(mem_root)
        store.remember("Decision: prefer Cloudflare Tunnel for Hawkeye UI", kind="decision")

        research_payload = {
            "query": "research Cloudflare Tunnel",
            "provider": "duckduckgo",
            "error": None,
            "sources": [
                {
                    "title": "Cloudflare Tunnel",
                    "url": "https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/",
                    "snippet": "Expose services without opening ports.",
                }
            ],
        }

        with mock.patch.object(ui_server, "_ollama_chat", return_value="Use a tunnel to loopback.") as ollama:
            with mock.patch("research.wants_research", return_value=True):
                with mock.patch("research.research") as res:
                    from research.web import ResearchResult, ResearchSource

                    res.return_value = ResearchResult(
                        query="research Cloudflare Tunnel",
                        provider="duckduckgo",
                        sources=[
                            ResearchSource(
                                title=research_payload["sources"][0]["title"],
                                url=research_payload["sources"][0]["url"],
                                snippet=research_payload["sources"][0]["snippet"],
                            )
                        ],
                    )
                    out = ui_server.handle_chat(
                        "research Cloudflare Tunnel for Hawkeye",
                        seed_notion=False,
                    )
        self.assertTrue(out["ok"])
        self.assertTrue(out["memory_id"])
        self.assertTrue(out["memory_hits"])
        self.assertTrue(out["research"]["sources"])
        system = ollama.call_args[0][1]
        self.assertIn("Relevant Hawkeye memory", system)
        self.assertIn("Web research", system)
        os.environ.pop("HAWKEYE_EMBED_FORCE_HASH", None)

if __name__ == "__main__":
    unittest.main()
