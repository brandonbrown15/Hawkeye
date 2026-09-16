#!/usr/bin/env python3
"""Browser Notion sign-in (OAuth), like a plugin connect button.

Flow:
  1. Opens Notion authorize page in your browser
  2. You click Allow + pick pages
  3. Notion redirects to http://127.0.0.1:8765/callback
  4. We save NOTION_TOKEN into .env

One-time parent setup (only once for the family):
  Create a *Public* Notion integration at https://www.notion.so/my-integrations
  Redirect URI: http://127.0.0.1:8765/callback
  Put OAuth client id + secret in .env as:
    NOTION_OAUTH_CLIENT_ID=...
    NOTION_OAUTH_CLIENT_SECRET=...
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PORT = int(os.environ.get("NOTION_OAUTH_PORT", "8765"))
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
TOKEN_URL = "https://api.notion.com/v1/oauth/token"
AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_VERSION = "2022-06-28"


def load_dotenv() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def upsert_env(key: str, value: str) -> None:
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text().splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    os.environ[key] = value


def exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = json.dumps(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"Notion token exchange failed HTTP {e.code}: {detail}") from e


def run_oauth() -> int:
    load_dotenv()
    if not ENV_PATH.exists():
        example = ROOT / ".env.example"
        if example.exists():
            ENV_PATH.write_text(example.read_text())
        else:
            ENV_PATH.write_text("")

    client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NOTION_OAUTH_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print(
            """
Notion browser sign-in needs a one-time Public integration (like an app id).

Do this once (parent / first setup):
  1. Open https://www.notion.so/my-integrations
  2. New integration → type: Public
  3. Redirect URI: http://127.0.0.1:8765/callback
  4. Copy OAuth client id + client secret into .env:

     NOTION_OAUTH_CLIENT_ID=...
     NOTION_OAUTH_CLIENT_SECRET=...

  5. Re-run:  ./scripts/connect_notion.sh

After that, everyday use is just browser Allow — no more pasting secrets.
""".strip()
        )
        return 2

    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}
    error_box: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # quiet
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("state", [None])[0] != state:
                error_box["err"] = "Bad state (try again)"
                body = b"<h1>Oops</h1><p>Bad state. Close this tab and retry.</p>"
                self.send_response(400)
            elif "error" in qs:
                error_box["err"] = qs["error"][0]
                body = f"<h1>Denied</h1><p>{qs['error'][0]}</p>".encode()
                self.send_response(400)
            else:
                result["code"] = qs.get("code", [""])[0]
                body = (
                    b"<h1>Connected!</h1>"
                    b"<p>Notion is linked to Autocode. You can close this tab.</p>"
                )
                self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = {
        "owner": "user",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
    print("Opening Notion sign-in in your browser…")
    print(f"If it does not open, visit:\n  {url}\n")
    webbrowser.open(url)

    thread.join(timeout=300)
    server.server_close()

    if error_box.get("err"):
        print(f"FAIL: {error_box['err']}")
        return 1
    if not result.get("code"):
        print("FAIL: No auth code received (timed out?). Re-run ./scripts/connect_notion.sh")
        return 1

    token_payload = exchange_code(result["code"], client_id, client_secret)
    access = token_payload.get("access_token", "").strip()
    if not access:
        print(f"FAIL: No access_token in response: {token_payload}")
        return 1

    upsert_env("NOTION_TOKEN", access)
    workspace = token_payload.get("workspace_name") or token_payload.get("workspace_id") or ""
    bot = token_payload.get("bot_id") or ""
    if workspace:
        upsert_env("NOTION_WORKSPACE", str(workspace))
    if bot:
        upsert_env("NOTION_BOT_ID", str(bot))

    # Optional refresh token for later renewals
    refresh = token_payload.get("refresh_token")
    if refresh:
        upsert_env("NOTION_REFRESH_TOKEN", str(refresh))

    print("✓ Notion connected. Token saved to .env as NOTION_TOKEN")
    if workspace:
        print(f"  workspace: {workspace}")
    print("Next: pick/share your Autocode Hub page, then ./start (or provision DBs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_oauth())
