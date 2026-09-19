#!/usr/bin/env python3
"""Tests for WhatsApp Cloud API webhook, parse, and notify triggers."""

from __future__ import annotations

import hashlib
import hmac
import io
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

from whatsapp import config, history, notify, parse, send, service, webhook  # noqa: E402
from whatsapp.webhook import WebhookError  # noqa: E402


SAMPLE_INBOUND = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "10987654321"},
                        "contacts": [{"profile": {"name": "Brandon"}, "wa_id": "15551234567"}],
                        "messages": [
                            {
                                "from": "15551234567",
                                "id": "wamid.TEST1",
                                "timestamp": "1710000000",
                                "type": "text",
                                "text": {"body": "Status on the tunnel?"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}

STATUS_ONLY = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "statuses": [{"id": "wamid.STAT", "status": "delivered"}],
                    },
                }
            ]
        }
    ],
}


class WhatsAppCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-wa-"))
        self._env = {k: os.environ.get(k) for k in (
            "HAWKEYE_WHATSAPP_DIR",
            "HAWKEYE_WHATSAPP_ENABLED",
            "HAWKEYE_WHATSAPP_REQUIRE_SIGNATURE",
            "HAWKEYE_WHATSAPP_NOTIFY_RULES",
            "HAWKEYE_WHATSAPP_NOTIFY_QUEUE_EMPTY",
            "HAWKEYE_WHATSAPP_NOTIFY_BLOCKED",
            "HAWKEYE_WHATSAPP_NOTIFY_HUMAN",
            "HAWKEYE_WHATSAPP_NOTIFY_DIGEST",
            "HAWKEYE_WHATSAPP_NOTIFY_DEDUP_SEC",
            "HAWKEYE_WHATSAPP_NOTIFY_TEMPLATE",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_VERIFY_TOKEN",
            "WHATSAPP_APP_SECRET",
            "WHATSAPP_ALLOWED_NUMBERS",
            "AUTOCODE_PUBLIC_HOST",
            "AUTOCODE_PRIVATE_MODE",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["HAWKEYE_WHATSAPP_DIR"] = str(self.tmp)
        os.environ["HAWKEYE_WHATSAPP_ENABLED"] = "1"
        os.environ["HAWKEYE_WHATSAPP_NOTIFY_DEDUP_SEC"] = "0"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "10987654321"
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "ea_test_token"
        os.environ["WHATSAPP_VERIFY_TOKEN"] = "verify-me"
        os.environ["WHATSAPP_APP_SECRET"] = "app-secret-test"
        os.environ["WHATSAPP_ALLOWED_NUMBERS"] = "+1 (555) 123-4567"
        os.environ["AUTOCODE_PUBLIC_HOST"] = "hawkeye.brownhawke.engineering"
        notify._RECENT.clear()

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        notify._RECENT.clear()


class VerifyTests(WhatsAppCase):
    def test_subscription_challenge(self) -> None:
        qs = {
            "hub.mode": ["subscribe"],
            "hub.verify_token": ["verify-me"],
            "hub.challenge": ["challenge-42"],
        }
        self.assertEqual(webhook.verify_subscription(qs), "challenge-42")
        code, body, ctype = webhook.handle_verify_request(qs)
        self.assertEqual(code, 200)
        self.assertEqual(body, b"challenge-42")
        self.assertIn("text/plain", ctype)

    def test_subscription_rejects_bad_token(self) -> None:
        qs = {
            "hub.mode": ["subscribe"],
            "hub.verify_token": ["nope"],
            "hub.challenge": ["x"],
        }
        with self.assertRaises(WebhookError):
            webhook.verify_subscription(qs)
        code, body, _ = webhook.handle_verify_request(qs)
        self.assertEqual(code, 403)
        self.assertEqual(body, b"forbidden")

    def test_signature_roundtrip(self) -> None:
        raw = json.dumps(SAMPLE_INBOUND).encode()
        digest = hmac.new(b"app-secret-test", raw, hashlib.sha256).hexdigest()
        webhook.verify_signature(raw, headers={"X-Hub-Signature-256": f"sha256={digest}"})
        with self.assertRaises(WebhookError):
            webhook.verify_signature(raw, headers={"X-Hub-Signature-256": "sha256=00" * 16})
        with self.assertRaises(WebhookError):
            webhook.verify_signature(raw, headers={})


class ParseTests(WhatsAppCase):
    def test_parse_text_and_ignore_status(self) -> None:
        msgs = parse.parse_inbound(SAMPLE_INBOUND)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].from_phone, "15551234567")
        self.assertEqual(msgs[0].text, "Status on the tunnel?")
        self.assertEqual(msgs[0].message_id, "wamid.TEST1")
        self.assertTrue(msgs[0].is_text)
        self.assertEqual(parse.parse_inbound(STATUS_ONLY), [])

    def test_allowlist(self) -> None:
        self.assertEqual(config.allowed_numbers(), ["15551234567"])
        self.assertTrue(config.number_allowed("15551234567"))
        self.assertTrue(config.number_allowed("+1-555-123-4567"))
        self.assertFalse(config.number_allowed("19999999999"))
        os.environ["WHATSAPP_ALLOWED_NUMBERS"] = "15551234567, +44 7911 123456"
        self.assertEqual(config.allowed_numbers(), ["15551234567", "447911123456"])
        os.environ["WHATSAPP_ALLOWED_NUMBERS"] = ""
        self.assertFalse(config.number_allowed("15551234567"))


class NotifyTests(WhatsAppCase):
    def test_default_rules(self) -> None:
        self.assertTrue(notify.rule_enabled("queue_empty"))
        self.assertTrue(notify.rule_enabled("ready_drained"))
        self.assertTrue(notify.rule_enabled("blocked"))
        self.assertTrue(notify.rule_enabled("human"))
        self.assertTrue(notify.rule_enabled("awaiting_operator"))
        self.assertFalse(notify.rule_enabled("digest"))

    def test_digest_opt_in_and_block_override(self) -> None:
        os.environ["HAWKEYE_WHATSAPP_NOTIFY_DIGEST"] = "1"
        os.environ["HAWKEYE_WHATSAPP_NOTIFY_BLOCKED"] = "0"
        self.assertTrue(notify.rule_enabled("digest"))
        self.assertFalse(notify.rule_enabled("blocked"))

    def test_notify_sends_mocked_http(self) -> None:
        captured: list[request.Request] = []

        class _Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=20):
            captured.append(req)
            return _Resp(json.dumps({"messages": [{"id": "wamid.OUT"}]}).encode())

        out = notify.notify_operator("queue_empty", "Ready queue drained.", opener=fake_open)
        self.assertTrue(out["ok"])
        self.assertEqual(out["sent"], 1)
        self.assertEqual(len(captured), 1)
        body = json.loads(captured[0].data.decode())
        self.assertEqual(body["to"], "15551234567")
        self.assertIn("Ready queue", body["text"]["body"])
        self.assertIn("graph.facebook.com", captured[0].full_url)

    def test_notify_skips_disabled_rule(self) -> None:
        os.environ["HAWKEYE_WHATSAPP_NOTIFY_DIGEST"] = "0"
        called = []
        out = notify.notify_operator("digest", "cycle done", opener=lambda *a, **k: called.append(1))
        self.assertTrue(out.get("skipped"))
        self.assertEqual(called, [])

    def test_blocked_sink_trigger(self) -> None:
        class Inner:
            def __init__(self) -> None:
                self.blocked_ids: list[str] = []
                self.escalations: list[str] = []

            def blocked(self, page_id: str) -> None:
                self.blocked_ids.append(page_id)

            def escalate(self, name, why, context, send_to="Human", pr=None) -> None:
                self.escalations.append(send_to)

        inner = Inner()
        sink = notify.wrap_sink(inner)
        with mock.patch.object(notify, "notify_operator") as ping:
            sink.blocked("page-1")
            sink.escalate("HK-1", "Ambiguous", "need approval", send_to="Human")
            sink.escalate("HK-2", "Too complex", "cloud", send_to="Cursor Cloud")
        self.assertEqual(inner.blocked_ids, ["page-1"])
        kinds = [c.args[0] for c in ping.call_args_list]
        self.assertEqual(kinds, ["blocked", "human"])


class InboundTests(WhatsAppCase):
    def test_inbound_maps_to_chat_and_replies(self) -> None:
        sent: list[tuple[str, str]] = []

        def fake_send(to, body, opener=None):
            sent.append((to, body))
            return {"ok": True, "id": "wamid.R"}

        chat_out = {
            "ok": True,
            "local_reply": "Tunnel is up on hawkeye.brownhawke.engineering.",
            "escalated": False,
            "cloud_reply": "",
        }
        raw = json.dumps(SAMPLE_INBOUND).encode()
        digest = hmac.new(b"app-secret-test", raw, hashlib.sha256).hexdigest()
        headers = {"X-Hub-Signature-256": f"sha256={digest}"}
        with mock.patch.object(send, "send_text", side_effect=fake_send):
            with mock.patch("ui.server.handle_chat", return_value=chat_out) as chat:
                out = service.handle_inbound_payload(raw, headers=headers, background=False)
        self.assertTrue(out["ok"])
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs.get("email") or chat.call_args[1].get("email"),
                         config.owner_email())
        self.assertIn("tunnel", chat.call_args.args[0].lower())
        self.assertEqual(sent[0][0], "15551234567")
        self.assertIn("Tunnel is up", sent[0][1])
        turns = history.load_history("15551234567")
        self.assertEqual(turns[-1]["role"], "assistant")

    def test_inbound_rejects_stranger(self) -> None:
        payload = json.loads(json.dumps(SAMPLE_INBOUND))
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "19990001111"
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"] = "wamid.STRANGER"
        raw = json.dumps(payload).encode()
        with mock.patch.object(send, "send_text") as send_mock:
            with mock.patch("ui.server.handle_chat") as chat:
                out = service.handle_inbound_payload(raw, skip_verify=True, background=False)
        self.assertTrue(out["accepted"][0]["rejected"])
        chat.assert_not_called()
        send_mock.assert_not_called()

    def test_send_text_mocked_graph(self) -> None:
        class _Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=20):
            self.assertIn("/10987654321/messages", req.full_url)
            self.assertIn("Bearer ea_test_token", req.get_header("Authorization") or req.headers.get("Authorization"))
            return _Resp(b'{"messages":[{"id":"wamid.X"}]}')

        out = send.send_text("15551234567", "hello", opener=fake_open)
        self.assertTrue(out["ok"])
        self.assertEqual(out["id"], "wamid.X")


class HttpWebhookTests(WhatsAppCase):
    def test_http_verify_and_signed_post(self) -> None:
        os.environ["AUTOCODE_PRIVATE_MODE"] = "1"
        from ui import auth as ui_auth
        from ui import server as ui_server

        httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = (
                f"http://127.0.0.1:{port}/api/webhooks/whatsapp"
                "?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=abc123"
            )
            with request.urlopen(url, timeout=5) as resp:
                self.assertEqual(resp.read().decode(), "abc123")

            bad = (
                f"http://127.0.0.1:{port}/api/webhooks/whatsapp"
                "?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=abc123"
            )
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(bad, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

            raw = json.dumps(STATUS_ONLY).encode()
            digest = hmac.new(b"app-secret-test", raw, hashlib.sha256).hexdigest()
            req = request.Request(
                f"http://127.0.0.1:{port}/api/webhooks/whatsapp",
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": f"sha256={digest}",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            self.assertTrue(body["ok"])
            self.assertTrue(body.get("ignored"))

            forged = request.Request(
                f"http://127.0.0.1:{port}/api/webhooks/whatsapp",
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=deadbeef",
                },
                method="POST",
            )
            with self.assertRaises(error.HTTPError) as ctx:
                request.urlopen(forged, timeout=5)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()
            ui_auth.clear_sessions()


class ConnectionsWhatsAppTests(WhatsAppCase):
    def test_provider_exposes_webhook_url(self) -> None:
        from ui import accounts, auth as ui_auth, connections

        os.environ["HAWKEYE_ACCOUNTS_DIR"] = str(self.tmp / "acct")
        os.environ["HAWKEYE_MEMORY_KEY"] = "test-secrets-key-for-unit-tests"
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        ui_auth.clear_users_cache()
        accounts.clear_cache()
        listed = connections.list_connections("brandon@brownhawke.engineering")
        wa = listed["providers"]["whatsapp"]
        self.assertEqual(
            wa["webhook_url"],
            "https://hawkeye.brownhawke.engineering/api/webhooks/whatsapp",
        )
        self.assertIn("phone_number_id", wa["fields"])
        self.assertIn("verify_token", wa["fields"])


if __name__ == "__main__":
    unittest.main()
