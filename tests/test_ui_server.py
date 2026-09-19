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
            "CURSOR_API_KEY",
            "GROK_BOT_WEBHOOK_URL",
            "XAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "AUTOCODE_DISABLE_METERED_GROK",
            "AUTOCODE_DELEGATE_TIMEOUT_SEC",
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_RUNTIME_FILE",
            "HAWKEYE_ACCOUNTS_DIR",
            "HAWKEYE_MEMORY_KEY",
            "AUTOCODE_CURSOR_DELEGATE_CMD",
            "AUTOCODE_GROK_DELEGATE_CMD",
            "HAWKEYE_CHAT_OLLAMA_TIMEOUT_SEC",
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

    def test_readiness_counts_account_connections_without_contextvar(self) -> None:
        """Live bug: checklist skip despite Connections save.

        has_secret() used ContextVar only. readiness(user=) never passed email,
        and 'stub' in AUTOCODE_*_DELEGATE_CMD forced ok=False even with a vault URL.
        """
        from ui import accounts, connections

        os.environ["HAWKEYE_ACCOUNTS_DIR"] = str(self.tmp / "accounts")
        os.environ["HAWKEYE_MEMORY_KEY"] = "ready-secret-key"
        os.environ["AUTOCODE_LOCAL_ONLY"] = "0"
        os.environ["AUTOCODE_CURSOR_DELEGATE_CMD"] = "./scripts/delegate_cursor_stub.sh"
        os.environ["AUTOCODE_GROK_DELEGATE_CMD"] = "./scripts/delegate_grok_stub.sh"
        os.environ.pop("CURSOR_WEBHOOK_URL", None)
        os.environ.pop("CURSOR_API_KEY", None)
        os.environ.pop("GROK_BOT_WEBHOOK_URL", None)
        accounts.clear_cache()
        brandon = "brandon@brownhawke.engineering"
        connections.set_connection(
            brandon,
            "cursor",
            secrets={
                "api_key": "key",
                "webhook_url": "https://example.invalid/cursor",
                "webhook_token": "tok",
            },
        )
        connections.set_connection(
            brandon,
            "grok",
            secrets={
                "webhook_url": "https://example.invalid/grok",
                "webhook_token": "gtok",
                "api_key": "xai",
            },
        )
        connections.set_request_user(None)
        with mock.patch.object(ui_server.health_mod, "check_local_stack") as chk:
            chk.return_value = mock.Mock(
                hermes_ok=True,
                ollama_ok=True,
                ollama_model="coder-64k",
                details=[],
            )
            anon = ui_server.readiness()
            signed = ui_server.readiness(user=brandon)
        by_anon = {c["id"]: c for c in anon["checks"]}
        by_user = {c["id"]: c for c in signed["checks"]}
        self.assertFalse(by_anon["cursor"]["ok"])
        self.assertFalse(by_anon["grok"]["ok"])
        self.assertTrue(by_user["cursor"]["ok"])
        self.assertTrue(by_user["grok"]["ok"])

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
        hermes = next(c for c in data["checks"] if c["id"] == "hermes")
        self.assertTrue(hermes.get("optional"))
        ollama = next(c for c in data["checks"] if c["id"] == "ollama")
        self.assertIn("Wake Ollama", ollama["hint"])
        hub = next(c for c in data["checks"] if c["id"] == "hub")
        self.assertIn("Machine", hub["hint"])

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
            self.assertIn("connectionsBtn", html)
            self.assertIn("chatEmpty", html)
            self.assertIn("chatStatus", html)
            self.assertIn("Talk to Hawkeye", html)
            self.assertIn("Queue work, then talk to Hawkeye", html)
            self.assertIn("queueForm", html)
            self.assertIn("chatSend", html)
            self.assertIn("Libre+Baskerville", html)
            self.assertIn("pane-switch", html)
            self.assertIn('data-pane-view="chat"', html)

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
            # Even with AUTOCODE_UI_SECURE=1, loopback HTTP must not get Secure
            # cookies or browsers drop the session and login appears to fail.
            os.environ["AUTOCODE_UI_SECURE"] = "1"
            with request.urlopen(good, timeout=5) as resp:
                out = json.loads(resp.read().decode())
                cookie = resp.headers.get("Set-Cookie", "")
            self.assertTrue(out["ok"])
            self.assertIn("hawkeye_session=", cookie)
            self.assertNotIn("Secure", cookie)

            status_req = request.Request(
                f"http://127.0.0.1:{port}/api/status",
                headers={"Cookie": cookie.split(";", 1)[0]},
            )
            with request.urlopen(status_req, timeout=5) as resp:
                snap = json.loads(resp.read().decode())
            self.assertIn("token", snap)

            via_tunnel = request.Request(
                f"http://127.0.0.1:{port}/api/login",
                data=json.dumps(
                    {
                        "email": "brandon@brownhawke.engineering",
                        "password": "secret-pass",
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Forwarded-Proto": "https",
                    "Host": "hawkeye.brownhawke.engineering",
                },
                method="POST",
            )
            with request.urlopen(via_tunnel, timeout=5) as resp:
                tunnel_cookie = resp.headers.get("Set-Cookie", "")
            self.assertIn("Secure", tunnel_cookie)
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

    def test_chat_wakes_ollama_on_connection_refused(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "1"
        calls = {"n": 0}

        def flaky_ollama(message: str, system: str, *, history=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("[Errno 111] Connection refused")
            return "OK — coder is awake"

        with mock.patch.object(ui_server, "_ollama_chat", side_effect=flaky_ollama):
            with mock.patch(
                "ui.machine_settings.ensure_ollama",
                return_value={"ok": True, "reachable": True},
            ) as wake:
                out = ui_server.handle_chat("ping", seed_notion=False)
        wake.assert_called_once()
        self.assertTrue(out["ok"])
        self.assertEqual(out["local_reply"], "OK — coder is awake")
        self.assertEqual(calls["n"], 2)

    def test_chat_history_passed_to_ollama(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "1"
        captured: dict = {}

        def fake_ollama(message: str, system: str, *, history=None):
            captured["message"] = message
            captured["system"] = system
            captured["history"] = history
            return "Hawkeye is the private BrownHawke Jetson assistant with UI, Ollama, and Notion boards."

        with mock.patch.object(ui_server, "_ollama_chat", side_effect=fake_ollama):
            out = ui_server.handle_chat(
                "I sent it to you?",
                seed_notion=False,
                history=[
                    {"role": "user", "content": "review https://github.com/brandonbrown15/Hawkeye"},
                    {"role": "assistant", "content": "Please provide the repository URL"},
                ],
            )
        self.assertTrue(out["ok"])
        self.assertIn("brandonbrown15/Hawkeye", captured["system"])
        self.assertEqual(len(captured["history"]), 2)
        self.assertEqual(captured["history"][0]["content"], "review https://github.com/brandonbrown15/Hawkeye")

    def test_stuck_url_loop_escalates(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        hist = [
            {"role": "user", "content": "https://github.com/brandonbrown15/Hawkeye"},
            {"role": "assistant", "content": "Please provide the repository URL"},
        ]
        with mock.patch.object(
            ui_server,
            "_ollama_chat",
            return_value="Please provide the repository URL so I can review it.",
        ):
            with mock.patch(
                "integrations.cursor_cloud.escalate_chat",
                return_value="Review started on Cursor",
            ) as esc:
                out = ui_server.handle_chat(
                    "I sent it to you?",
                    seed_notion=False,
                    history=hist,
                )
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        esc.assert_called_once()

    def test_repo_review_ask_escalates(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        with mock.patch.object(ui_server, "_ollama_chat", return_value="I can try a shallow look locally."):
            with mock.patch(
                "integrations.cursor_cloud.escalate_chat",
                return_value="Cloud review",
            ) as esc:
                out = ui_server.handle_chat(
                    "Can you review the GitHub repo Hawkeye please",
                    seed_notion=False,
                )
        self.assertTrue(out["escalated"])
        esc.assert_called_once()

    def test_normalize_chat_history(self) -> None:
        hist = ui_server._normalize_chat_history(
            [
                {"role": "you", "content": "hi"},
                {"role": "local", "content": "hello"},
                {"role": "system", "content": "ignore"},
                {"role": "user", "content": ""},
            ]
        )
        self.assertEqual(hist, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])

    def test_chat_escalates_to_cursor_webhook(self) -> None:
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        os.environ.pop("CURSOR_API_KEY", None)
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"

        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: too hard"):
            with mock.patch.object(ui_server, "_webhook_chat", return_value="premium plan") as wh:
                out = ui_server.handle_chat("redesign the multi-service architecture", seed_notion=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        self.assertEqual(out["cloud_reply"], "premium plan")
        wh.assert_called_once()

    def test_cloud_chat_none_explains_metered_grok_block(self) -> None:
        os.environ["XAI_API_KEY"] = "xai-saved"
        os.environ["AUTOCODE_DISABLE_METERED_GROK"] = "1"
        os.environ.pop("CURSOR_API_KEY", None)
        os.environ.pop("CURSOR_WEBHOOK_URL", None)
        os.environ.pop("GROK_BOT_WEBHOOK_URL", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        reply, provider = ui_server._cloud_chat("hard", "ESCALATE: too hard")
        self.assertEqual(provider, "none")
        self.assertIn("AUTOCODE_DISABLE_METERED_GROK", reply)
        self.assertIn("No usable premium provider", reply)

    def test_cloud_chat_none_says_failed_not_unconfigured(self) -> None:
        os.environ["CURSOR_WEBHOOK_URL"] = "http://127.0.0.1:1/missing-bridge"
        os.environ.pop("CURSOR_API_KEY", None)
        os.environ["AUTOCODE_DELEGATE_TIMEOUT_SEC"] = "1"
        reply, provider = ui_server._cloud_chat("hard", "ESCALATE: too hard")
        self.assertEqual(provider, "none")
        self.assertIn("Premium provider(s) failed", reply)
        self.assertNotIn("No usable premium provider", reply)

    def test_chat_escalates_to_cursor_api_key(self) -> None:
        os.environ["CURSOR_API_KEY"] = "test-cursor-key"
        os.environ.pop("CURSOR_WEBHOOK_URL", None)
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"

        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: too hard"):
            with mock.patch(
                "integrations.cursor_cloud.escalate_chat",
                return_value="Cloud agent: https://cursor.com/agents/bc-1",
            ) as api:
                out = ui_server.handle_chat("redesign the multi-service architecture", seed_notion=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        self.assertIn("cursor.com/agents", out["cloud_reply"])
        api.assert_called_once()

    def test_chat_local_only_skips_cloud(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "1"
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        os.environ.pop("CURSOR_API_KEY", None)
        with mock.patch.object(ui_server, "_ollama_chat", return_value="ESCALATE: nope"):
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                out = ui_server.handle_chat("hard thing", seed_notion=False)
        cloud.assert_not_called()
        self.assertFalse(out["escalated"])
        self.assertTrue(out["local_only"])

    def test_runtime_local_only_toggle_overrides_env(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_WEBHOOK_URL"] = "http://example.invalid/cursor"
        os.environ.pop("CURSOR_API_KEY", None)
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

    def test_chat_timeout_does_not_wake_ollama(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "1"
        with mock.patch.object(
            ui_server,
            "_ollama_chat",
            side_effect=TimeoutError("timed out"),
        ):
            with mock.patch("ui.machine_settings.ensure_ollama") as wake:
                out = ui_server.handle_chat("Hi", seed_notion=False)
        wake.assert_not_called()
        self.assertTrue(out.get("local_error"))
        self.assertFalse(out["escalated"])

    def test_greeting_hi_does_not_escalate_when_ollama_down(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        with mock.patch.object(
            ui_server,
            "_ollama_chat",
            side_effect=TimeoutError("timed out"),
        ):
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                out = ui_server.handle_chat("Hi", seed_notion=False)
        cloud.assert_not_called()
        self.assertTrue(out["ok"])
        self.assertFalse(out["escalated"])
        self.assertIn("time", (out.get("local_error") or "").lower())
        self.assertFalse(out.get("cloud_error"))

    def test_greeting_hi_short_local_reply_does_not_escalate(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        with mock.patch.object(ui_server, "_ollama_chat", return_value="Hello."):
            with mock.patch.object(ui_server, "_cloud_chat") as cloud:
                out = ui_server.handle_chat("Hi", seed_notion=False)
        cloud.assert_not_called()
        self.assertFalse(out["escalated"])
        self.assertEqual(out["local_reply"], "Hello.")
        self.assertFalse(ui_server._should_escalate("Hi", "Hello."))

    def test_chat_ollama_timeout_is_bounded(self) -> None:
        os.environ.pop("HAWKEYE_CHAT_OLLAMA_TIMEOUT_SEC", None)
        self.assertEqual(ui_server._chat_ollama_timeout_sec(), 18.0)
        os.environ["HAWKEYE_CHAT_OLLAMA_TIMEOUT_SEC"] = "120"
        self.assertEqual(ui_server._chat_ollama_timeout_sec(), 45.0)
        os.environ["HAWKEYE_CHAT_OLLAMA_TIMEOUT_SEC"] = "2"
        self.assertEqual(ui_server._chat_ollama_timeout_sec(), 5.0)
        os.environ["HAWKEYE_CHAT_OLLAMA_TIMEOUT_SEC"] = "18"
        self.assertEqual(ui_server._chat_ollama_timeout_sec(), 18.0)

    def test_friendly_local_error_timeout_and_refused(self) -> None:
        self.assertIn("time", ui_server._friendly_local_error("timed out").lower())
        self.assertIn("ollama", ui_server._friendly_local_error("[Errno 111] Connection refused").lower())
        self.assertIn("unavailable", ui_server._friendly_local_error("boom").lower())

    def test_local_fail_hard_ask_still_escalates(self) -> None:
        os.environ["AUTOCODE_PERSONAL_LOCAL_ONLY"] = "0"
        os.environ["CURSOR_API_KEY"] = "test-key"
        with mock.patch.object(
            ui_server,
            "_ollama_chat",
            side_effect=TimeoutError("timed out"),
        ):
            with mock.patch.object(
                ui_server,
                "_cloud_chat",
                return_value=("Cloud plan", "Cursor"),
            ) as cloud:
                out = ui_server.handle_chat(
                    "redesign the multi-service architecture",
                    seed_notion=False,
                )
        cloud.assert_called_once()
        self.assertTrue(out["escalated"])
        self.assertEqual(out["provider"], "Cursor")
        self.assertFalse(out.get("cloud_error"))

    def test_chat_client_aborts_and_reenables_send(self) -> None:
        js = (ROOT / "ui/static/app.js").read_text(encoding="utf-8")
        self.assertIn("AbortController", js)
        self.assertIn("timeoutMs", js)
        self.assertIn("did not reply in time", js)
        self.assertIn("resetChatSend", js)
        html = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        self.assertIn("askHawkeye", html)
        self.assertIn("data-pane=\"board\"", html)
        self.assertIn("chat-composer", html)
        self.assertIn('id="chatSend"', html)
        self.assertIn("novalidate", html)
        self.assertIn("queueForm", html)
        self.assertIn("resetChatSend", js)
        self.assertIn("function applyBoardView", js)
        css = (ROOT / "ui/static/app.css").read_text(encoding="utf-8")
        self.assertIn("min-height: 0", css)
        self.assertIn(".chat-composer", css)
        self.assertIn("z-index: 5", css)
        self.assertIn("pointer-events: auto", css)
        self.assertIn("100dvh", css)
        self.assertNotIn("100dvh - 16rem", css)

    def test_overlay_close_is_explicit_and_not_blocked_by_nested_forms(self) -> None:
        html = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui/static/app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui/static/app.css").read_text(encoding="utf-8")
        self.assertIn('id="accountClose"', html)
        self.assertIn('type="button" class="btn ghost compact overlay-close" id="accountClose"', html)
        self.assertNotIn('method="dialog"', html)
        self.assertNotIn('value="close"', html)
        start = html.find('id="accountDialog"')
        end = html.find("</dialog>", start)
        dialog = html[start:end]
        self.assertIn('<div class="account-panel">', dialog)
        self.assertIn('id="newProjectForm"', dialog)
        self.assertIn('id="dmForm"', dialog)
        self.assertLess(dialog.find("<div"), dialog.find("<form"))
        self.assertIn("function closeAccount", js)
        self.assertIn("function closeTopOverlay", js)
        self.assertIn('ev.key !== "Escape"', js)
        self.assertIn("closeAccount()", js)
        self.assertIn("closeDrawer()", js)
        self.assertIn(".overlay-close", css)
        self.assertIn("pointer-events: auto", css)
        self.assertIn("z-index: 60", css)
        self.assertIn("Libre+Baskerville", html)
        self.assertIn("Libre Baskerville", css)
        self.assertIn("--navy: #002d62", css)
        self.assertIn("color-scheme: light", css)
        self.assertNotIn("IBM Plex Sans", html)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn('method="dialog"', html)

    def test_light_theme_and_pm_queue_shell(self) -> None:
        html = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        login = (ROOT / "ui/static/login.html").read_text(encoding="utf-8")
        css = (ROOT / "ui/static/app.css").read_text(encoding="utf-8")
        js = (ROOT / "ui/static/app.js").read_text(encoding="utf-8")
        self.assertIn("Liberation Serif", css)
        self.assertIn("--paper: #ffffff", css)
        self.assertIn("--paper: #0e1624", css)
        self.assertIn("--navy-fill: #002d62", css)
        self.assertIn("--navy-fill-hover: #001a3a", css)
        self.assertIn("Add to queue", html)
        self.assertIn('id="taskQueue"', html)
        self.assertIn('data-board-view="queue"', html)
        self.assertIn('id="hostStrip"', html)
        self.assertIn('id="hostOllama"', html)
        self.assertIn('id="themePref"', html)
        self.assertIn("Match device", html)
        self.assertIn("/api/host", js)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn('html[data-theme="dark"]', css)
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn("function applyTheme", js)
        self.assertIn("hawkeye-theme", js)
        self.assertIn('applyTheme("system")', js)
        self.assertIn("prefers-color-scheme: dark", js)
        self.assertIn('"/api/tasks"', js)
        self.assertIn("body.app", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("workspace-secondary", html)
        self.assertIn("Jetson replies only", html)
        for page in (html, login):
            self.assertIn("Libre+Baskerville", page)
            self.assertIn('localStorage.getItem("hawkeye-theme")', page)
            self.assertIn("prefers-color-scheme: dark", page)
            self.assertIn("data-theme", page)
            self.assertIn("#0e1624", page)

if __name__ == "__main__":
    unittest.main()
