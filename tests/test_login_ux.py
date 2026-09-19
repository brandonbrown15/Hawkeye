#!/usr/bin/env python3
"""Login UX, structured errors, users-file reload, HEAD, and accounts CLI."""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import auth as ui_auth  # noqa: E402
from ui import server as ui_server  # noqa: E402
from ui.accounts_cli import main as accounts_main  # noqa: E402


class LoginAuthUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-login-"))
        self.users = self.tmp / "users.json"
        self._env = {k: os.environ.get(k) for k in (
            "AUTOCODE_PRIVATE_MODE",
            "AUTOCODE_PRIVATE_USER",
            "AUTOCODE_PRIVATE_PASSWORD_HASH",
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "AUTOCODE_UI_SECURE",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["AUTOCODE_PRIVATE_MODE"] = "1"
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        os.environ["HAWKEYE_USERS_FILE"] = str(self.users)
        ui_auth.clear_users_cache()
        ui_auth.clear_sessions()
        self.users.write_text(
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
        ui_auth.clear_users_cache()

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_users_cache()
        ui_auth.clear_sessions()

    def test_canonicalize_email(self) -> None:
        self.assertEqual(
            ui_auth.canonicalize_email("  Mark@BrownHawke.Engineering  "),
            "mark@brownhawke.engineering",
        )
        self.assertEqual(ui_auth.canonicalize_email("mark"), "mark@brownhawke.engineering")
        self.assertTrue(ui_auth.is_allowed_email("mark"))

    def test_diagnose_codes(self) -> None:
        self.assertEqual(ui_auth.diagnose_login("", "").code, ui_auth.CODE_EMPTY)
        self.assertEqual(
            ui_auth.diagnose_login("mark@gmail.com", "x").code, ui_auth.CODE_BAD_DOMAIN
        )
        self.assertEqual(
            ui_auth.diagnose_login("mark@brownhawke.engineering", "x").code,
            ui_auth.CODE_UNKNOWN_ACCOUNT,
        )
        self.assertEqual(
            ui_auth.diagnose_login("brandon@brownhawke.engineering", "nope").code,
            ui_auth.CODE_WRONG_PASSWORD,
        )
        self.assertIsNone(ui_auth.diagnose_login("brandon@brownhawke.engineering", "secret-pass"))
        self.assertIsNone(ui_auth.diagnose_login("Brandon", "secret-pass"))

    def test_reload_users_on_mtime(self) -> None:
        self.assertIsNone(ui_auth.login("mark@brownhawke.engineering", "hunter2xx"))
        data = json.loads(self.users.read_text(encoding="utf-8"))
        data["users"]["mark@brownhawke.engineering"] = ui_auth.hash_password("hunter2xx")
        self.users.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        now = time.time() + 5
        os.utime(self.users, (now, now))
        token = ui_auth.login("mark@brownhawke.engineering", "hunter2xx")
        self.assertTrue(token)
        self.assertEqual(ui_auth.session_user(token), "mark@brownhawke.engineering")

    def test_upsert_and_list(self) -> None:
        out = ui_auth.upsert_user_password(
            "mark@brownhawke.engineering", "new-secret-1", users_file=self.users
        )
        self.assertTrue(out["created"])
        self.assertIn("mark@brownhawke.engineering", out["users"])
        raw = self.users.read_text(encoding="utf-8")
        self.assertNotIn("new-secret-1", raw)
        self.assertIn("pbkdf2_sha256$", raw)
        self.assertTrue(ui_auth.login("mark", "new-secret-1"))

    def test_clear_cookie_matches_secure(self) -> None:
        set_c = ui_auth.session_cookie_header("tok", secure=True)
        self.assertIn("Secure", set_c)
        self.assertIn("SameSite=Lax", set_c)
        clr = ui_auth.clear_session_cookie_header(secure=True)
        self.assertIn("Secure", clr)
        self.assertIn("Max-Age=0", clr)
        self.assertNotIn("Secure", ui_auth.clear_session_cookie_header(secure=False))

    def test_cloudflare_access_identity(self) -> None:
        none = ui_auth.cloudflare_access_identity({})
        self.assertFalse(none["cloudflare_access"])
        hit = ui_auth.cloudflare_access_identity(
            {"Cf-Access-Authenticated-User-Email": "mark@brownhawke.engineering"}
        )
        self.assertTrue(hit["cloudflare_access"])
        self.assertEqual(hit["access_email"], "mark@brownhawke.engineering")


class LoginHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-login-http-"))
        self.users = self.tmp / "users.json"
        self._env = {k: os.environ.get(k) for k in (
            "AUTOCODE_PRIVATE_MODE",
            "AUTOCODE_PRIVATE_USER",
            "AUTOCODE_PRIVATE_PASSWORD_HASH",
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "AUTOCODE_UI_SECURE",
            "AUTOCODE_PRODUCT_NAME",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["AUTOCODE_PRODUCT_NAME"] = "Hawkeye"
        os.environ["AUTOCODE_PRIVATE_MODE"] = "1"
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        os.environ["HAWKEYE_USERS_FILE"] = str(self.users)
        self.users.write_text(
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
        ui_auth.clear_users_cache()
        ui_auth.clear_sessions()
        self.httpd = ui_server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_users_cache()
        ui_auth.clear_sessions()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _post_login(self, payload: dict, headers: dict | None = None) -> tuple[int, dict, str]:
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        req = request.Request(
            self._url("/api/login"),
            data=json.dumps(payload).encode(),
            headers=hdrs,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
                return resp.status, body, resp.headers.get("Set-Cookie", "")
        except error.HTTPError as exc:
            body = json.loads(exc.read().decode())
            return exc.code, body, exc.headers.get("Set-Cookie", "") if exc.headers else ""

    def test_structured_login_errors(self) -> None:
        code, body, _ = self._post_login({"email": "mark@gmail.com", "password": "x"})
        self.assertEqual(code, 401)
        self.assertEqual(body["code"], "bad_domain")
        self.assertIn("error", body)

        code, body, _ = self._post_login(
            {"email": "mark@brownhawke.engineering", "password": "x"}
        )
        self.assertEqual(body["code"], "unknown_account")
        self.assertIn("set-password", body.get("hint", ""))

        code, body, _ = self._post_login(
            {"email": "brandon@brownhawke.engineering", "password": "nope"}
        )
        self.assertEqual(body["code"], "wrong_password")

        code, body, cookie = self._post_login(
            {"email": "  Brandon@BrownHawke.engineering ", "password": "secret-pass"}
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["user"], "brandon@brownhawke.engineering")
        self.assertIn("hawkeye_session=", cookie)
        self.assertNotIn("Secure", cookie)

        code, body, cookie = self._post_login(
            {"email": "brandon", "password": "secret-pass"},
            headers={"X-Forwarded-Proto": "https", "Host": "hawkeye.brownhawke.engineering"},
        )
        self.assertEqual(code, 200)
        self.assertIn("Secure", cookie)

    def test_login_html_ux_and_head(self) -> None:
        with request.urlopen(self._url("/login"), timeout=5) as resp:
            html = resp.read().decode()
        self.assertIn("pwToggle", html)
        self.assertIn("forgotHelp", html)
        self.assertIn("hawkeye accounts set-password", html)
        self.assertIn("novalidate", html)
        self.assertIn("credentials: \"same-origin\"", html)
        self.assertIn("brownhawke.engineering", html)

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("HEAD", "/login")
        head_login = conn.getresponse()
        self.assertEqual(head_login.status, 200)
        self.assertEqual(head_login.read(), b"")
        conn.request("HEAD", "/")
        head_root = conn.getresponse()
        self.assertEqual(head_root.status, 302)
        self.assertEqual(head_root.getheader("Location"), "/login")
        head_root.read()
        conn.request("OPTIONS", "/api/login")
        opt = conn.getresponse()
        self.assertEqual(opt.status, 204)
        opt.read()
        conn.close()

    def test_api_auth_access_flag_and_logout_secure(self) -> None:
        req = request.Request(
            self._url("/api/auth"),
            headers={"Cf-Access-Authenticated-User-Email": "mark@brownhawke.engineering"},
        )
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        self.assertTrue(data["cloudflare_access"])
        self.assertEqual(data["access_email"], "mark@brownhawke.engineering")
        self.assertEqual(data["login_emails"], [])  # do not leak on public endpoint
        self.assertGreaterEqual(data["configured_user_count"], 1)

        _, body, cookie = self._post_login(
            {"email": "brandon@brownhawke.engineering", "password": "secret-pass"},
            headers={"X-Forwarded-Proto": "https", "Host": "hawkeye.brownhawke.engineering"},
        )
        self.assertTrue(body["ok"])
        logout = request.Request(
            self._url("/api/logout"),
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Cookie": cookie.split(";", 1)[0],
                "X-Forwarded-Proto": "https",
                "Host": "hawkeye.brownhawke.engineering",
            },
            method="POST",
        )
        with request.urlopen(logout, timeout=5) as resp:
            clr = resp.headers.get("Set-Cookie", "")
        self.assertIn("Max-Age=0", clr)
        self.assertIn("Secure", clr)


class AccountsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hawkeye-cli-"))
        self.users = self.tmp / "users.json"
        self._env = {k: os.environ.get(k) for k in (
            "HAWKEYE_USERS_FILE",
            "HAWKEYE_USERS_JSON",
            "HAWKEYE_ALLOWED_EMAIL_DOMAIN",
            "AUTOCODE_PRIVATE_MODE",
        )}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["HAWKEYE_ALLOWED_EMAIL_DOMAIN"] = "brownhawke.engineering"
        os.environ["HAWKEYE_USERS_FILE"] = str(self.users)
        ui_auth.clear_users_cache()

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ui_auth.clear_users_cache()

    def test_set_password_list_check(self) -> None:
        rc = accounts_main(
            [
                "accounts",
                "set-password",
                "--email",
                "mark@brownhawke.engineering",
                "--password",
                "mark-pass-99",
                "--users-file",
                str(self.users),
            ]
        )
        self.assertEqual(rc, 0)
        stored = self.users.read_text(encoding="utf-8")
        self.assertNotIn("mark-pass-99", stored)
        self.assertIn("mark@brownhawke.engineering", stored)

        with mock.patch("builtins.print") as printed:
            rc = accounts_main(
                ["accounts", "list", "--users-file", str(self.users)]
            )
        self.assertEqual(rc, 0)
        joined = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("mark@brownhawke.engineering", joined)
        self.assertNotIn("pbkdf2", joined)

        rc = accounts_main(
            [
                "accounts",
                "check",
                "--email",
                "mark",
                "--password",
                "mark-pass-99",
                "--users-file",
                str(self.users),
            ]
        )
        self.assertEqual(rc, 0)
        rc = accounts_main(
            [
                "accounts",
                "check",
                "--email",
                "mark",
                "--password",
                "wrong-pass",
                "--users-file",
                str(self.users),
            ]
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
