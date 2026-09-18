#!/usr/bin/env python3
"""Local Autocode dashboard (stdlib only).

  python3 -m ui.server
  ./scripts/ui.sh

Default: 127.0.0.1:8787
Tunnel: ssh -L 8787:127.0.0.1:8787 jetson
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import health as health_mod  # noqa: E402
from orchestrator import ops  # noqa: E402
from ui import auth as ui_auth  # noqa: E402
from ui import runtime_settings as runtime  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
STATE = ROOT / "state"
LOGS = ROOT / "logs"

HOST = os.environ.get("AUTOCODE_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("AUTOCODE_UI_PORT", "8787"))
TOKEN = secrets.token_urlsafe(24)

# Paths that stay reachable without a private session (assets + login).
_PUBLIC_GET = {
    "/login",
    "/login.html",
    "/app.css",
    "/api/auth",
}
_PUBLIC_POST = {
    "/api/login",
    "/api/webhooks/resend",
}

_demo_lock = threading.Lock()
_demo_proc: subprocess.Popen[str] | None = None
_demo_log = STATE / "ui-demo.log"
_work_lock = threading.Lock()
_work_proc: subprocess.Popen[str] | None = None
_work_log = STATE / "ui-work.log"


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def json_response(data: Any, code: int = 200) -> tuple[int, bytes, str]:
    return code, json.dumps(data, indent=2).encode(), "application/json; charset=utf-8"


def env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def has_env(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _ready_secret(provider: str, field: str) -> bool:
    try:
        from ui import connections

        return connections.has_secret(provider, field)
    except Exception:  # noqa: BLE001
        return False


def gh_authed() -> bool:
    try:
        r = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=8, cwd=ROOT
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def readiness(*, user: str | None = None) -> dict[str, Any]:
    hermes_ok = False
    ollama_ok = False
    model = os.environ.get("OLLAMA_MODEL", "coder-64k")
    try:
        report = health_mod.check_local_stack()
        hermes_ok = report.hermes_ok
        ollama_ok = report.ollama_ok
        model = report.ollama_model
        details = list(report.details)
    except Exception as e:  # noqa: BLE001
        details = [f"health check error: {e}"]

    cursor_cmd = os.environ.get("AUTOCODE_CURSOR_DELEGATE_CMD", "")
    grok_cmd = os.environ.get("AUTOCODE_GROK_DELEGATE_CMD", "")
    # Autopilot/cloud readiness uses global LOCAL_ONLY (not per-user chat toggle).
    runtime_data = runtime.load()
    if "local_only" in runtime_data:
        local_only = runtime.autopilot_local_only()
    else:
        local_only = env_truthy("AUTOCODE_LOCAL_ONLY", "1")

    checks = [
        {"id": "env", "label": ".env present", "ok": (ROOT / ".env").exists(), "hint": "Run ./start"},
        {
            "id": "notion",
            "label": "Notion connected",
            "ok": _ready_secret("notion", "token"),
            "hint": "Account → Connections → Notion (or ./scripts/connect_notion.sh)",
        },
        {
            "id": "hub",
            "label": "Notion hub / DBs",
            "ok": has_env("NOTION_BUILD_QUEUE_DB") or has_env("NOTION_HUB_PAGE"),
            "hint": "Share Autocode Hub page",
        },
        {
            "id": "github",
            "label": "GitHub token",
            "ok": _ready_secret("github", "token") or gh_authed(),
            "hint": "Account → Connections → GitHub (or ./scripts/auth_github.sh)",
        },
        {"id": "hermes", "label": "Hermes CLI", "ok": hermes_ok, "hint": "./hermes/install_hermes.sh"},
        {"id": "ollama", "label": f"Ollama ({model})", "ok": ollama_ok, "hint": "./ollama/install_ollama_jetson.sh"},
        {
            "id": "cursor",
            "label": "Cursor webhook",
            "ok": local_only
            or (
                _ready_secret("cursor", "webhook_url")
                and "stub" not in cursor_cmd
            ),
            "hint": "Account → Connections → Cursor (or keep LOCAL_ONLY=1)",
            "optional": True,
        },
        {
            "id": "grok",
            "label": "Grok Bot webhook",
            "ok": local_only
            or (
                _ready_secret("grok", "webhook_url")
                and "stub" not in grok_cmd
            ),
            "hint": "Account → Connections → Grok (or keep LOCAL_ONLY=1)",
            "optional": True,
        },
        {
            "id": "autopilot",
            "label": "Autopilot enabled",
            "ok": env_truthy("AUTOCODE_AUTOPILOT_ENABLED"),
            "hint": "Set AUTOCODE_AUTOPILOT_ENABLED=1 after a supervised run",
            "optional": True,
        },
        {
            "id": "continuous",
            "label": "Always-on project autopilot",
            "ok": env_truthy("AUTOCODE_CONTINUOUS_ENABLED"),
            "hint": "Set AUTOCODE_CONTINUOUS_ENABLED=1 to keep draining Ready tasks until finished",
            "optional": True,
        },
        {
            "id": "memory",
            "label": "Vector memory (SSD)",
            "ok": env_truthy("HAWKEYE_MEMORY_ENABLED", "1"),
            "hint": "HAWKEYE_MEMORY_DIR under AUTOCODE_DATA_ROOT/hawkeye/memory",
            "optional": True,
        },
        {
            "id": "research",
            "label": "Web research (deep page read)",
            "ok": env_truthy("HAWKEYE_RESEARCH_ENABLED", "1"),
            "hint": "Account → Connections → Brave; HAWKEYE_RESEARCH_DEEP=1 fetches pages",
            "optional": True,
        },
        {
            "id": "mail",
            "label": "Email inbox (Resend)",
            "ok": (not env_truthy("HAWKEYE_MAIL_ENABLED"))
            or (
                has_env("RESEND_API_KEY")
                and (has_env("RESEND_WEBHOOK_SECRET") or env_truthy("HAWKEYE_MAIL_ALLOW_UNSIGNED"))
            ),
            "hint": "Account → Connections or .env: HAWKEYE_MAIL_ENABLED + Resend keys",
            "optional": True,
        },
        {
            "id": "auto_update",
            "label": "Jetson auto-update timer",
            "ok": (ROOT / "scripts" / "hawkeye_self_update.sh").is_file(),
            "hint": "./scripts/install_hawkeye_autostart.sh (hawkeye-update.timer every 5 min)",
            "optional": True,
        },
    ]
    if ui_auth.private_mode_enabled():
        checks.append(
            {
                "id": "private_auth",
                "label": f"Work login (@{ui_auth.allowed_email_domain()})",
                "ok": ui_auth.credentials_ready(),
                "hint": "python3 scripts/set_work_user.py --email you@brownhawke.engineering",
            }
        )
    memory_stats: dict[str, Any] | None = None
    if env_truthy("HAWKEYE_MEMORY_ENABLED", "1"):
        try:
            from memory import get_store

            memory_stats = get_store().stats()
        except Exception as e:  # noqa: BLE001
            memory_stats = {"error": str(e)}
    return {
        "ready": all(c["ok"] for c in checks if not c.get("optional")),
        "local_only": local_only,
        "personal_local_only": ui_auth.personal_local_only(user),
        "settings_user": runtime.normalize_user(user),
        "private_mode": ui_auth.private_mode_enabled(),
        "product": ui_auth.product_name(),
        "public_host": ui_auth.public_host(),
        "autopilot": env_truthy("AUTOCODE_AUTOPILOT_ENABLED"),
        "continuous": env_truthy("AUTOCODE_CONTINUOUS_ENABLED"),
        "checks": checks,
        "details": details,
        "cost_profile": os.environ.get("AUTOCODE_COST_PROFILE", "cursor-grok"),
        "memory": memory_stats,
    }


def snapshot() -> dict[str, Any]:
    status = ops.load_status()
    control = ops.load_control()
    return {
        "status": asdict(status),
        "control": asdict(control),
        "heartbeat_age_sec": status.age_seconds(),
        "stuck": status.looks_stuck(),
        "formatted": ops.format_status(status, control),
        "token": TOKEN,
    }


def latest_log_tail(n: int = 80) -> dict[str, Any]:
    candidates: list[Path] = []
    if LOGS.is_dir():
        candidates.extend(LOGS.glob("nightly-*.log"))
        candidates.extend(LOGS.glob("*.log"))
    if _demo_log.exists():
        candidates.append(_demo_log)
    if not candidates:
        return {"path": None, "lines": [], "text": "(no logs yet — run a mock cycle)"}
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return {"path": str(path), "lines": [], "text": f"(unreadable: {e})"}
    lines = text.splitlines()[-n:]
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    return {"path": rel, "lines": lines, "text": "\n".join(lines)}


def demo_state() -> dict[str, Any]:
    with _demo_lock:
        running = _demo_proc is not None and _demo_proc.poll() is None
        code = None if _demo_proc is None else _demo_proc.poll()
    return {
        "running": running,
        "exit_code": code,
        "log": str(_demo_log.relative_to(ROOT)) if _demo_log.exists() else None,
    }


def start_demo() -> dict[str, Any]:
    global _demo_proc
    with _demo_lock:
        if _demo_proc is not None and _demo_proc.poll() is None:
            return {"ok": False, "error": "Demo already running", **demo_state()}
        STATE.mkdir(parents=True, exist_ok=True)
        logf = _demo_log.open("w")
        script = ROOT / "scripts" / "demo_night.sh"
        cmd = (
            [str(script)]
            if script.exists()
            else [sys.executable, "-m", "orchestrator.run_night", "--mock"]
        )
        _demo_proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, text=True, env={**os.environ}
        )
        ops.write_status(
            phase="starting",
            detail="UI started mock demo cycle",
            night_id=f"ui-demo-{int(time.time())}",
        )
        ops.telegram_notify("Autocode UI: mock demo cycle started")
    return {"ok": True, **demo_state()}


def work_state() -> dict[str, Any]:
    with _work_lock:
        running = _work_proc is not None and _work_proc.poll() is None
        code = None if _work_proc is None else _work_proc.poll()
    return {
        "running": running,
        "exit_code": code,
        "log": str(_work_log.relative_to(ROOT)) if _work_log.exists() else None,
    }


def start_work_cycle(force: bool = True) -> dict[str, Any]:
    """Kick a live (or mock) continuous work cycle from the UI."""
    global _work_proc
    with _work_lock:
        if _work_proc is not None and _work_proc.poll() is None:
            return {"ok": False, "error": "Work cycle already running", **work_state()}
        if _demo_proc is not None and _demo_proc.poll() is None:
            return {"ok": False, "error": "Demo is running — wait or abort", **work_state()}
        STATE.mkdir(parents=True, exist_ok=True)
        logf = _work_log.open("w")
        script = ROOT / "cron" / "worker_run.sh"
        cmd = [str(script)]
        if force:
            cmd.append("--force")
        _work_proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, text=True, env={**os.environ}
        )
        ops.write_status(
            phase="starting",
            detail="UI started work cycle",
            night_id=f"ui-work-{int(time.time())}",
        )
        ops.telegram_notify("Autocode UI: work cycle started")
    return {"ok": True, **work_state()}


def apply_control(action: str, note: str = "", task_id: str = "") -> dict[str, Any]:
    action = action.strip().lower()
    if action == "pause":
        ops.set_control(paused=True, note=note or "paused from UI")
        ops.telegram_notify(f"Autocode PAUSED (UI): {note or 'paused from UI'}")
    elif action == "resume":
        ops.set_control(paused=False, note="")
        ops.telegram_notify("Autocode RESUMED (UI)")
    elif action == "abort":
        ops.set_control(abort=True, note=note or "abort from UI")
        ops.telegram_notify("Autocode ABORT requested from UI")
    elif action == "skip":
        if not task_id:
            return {"ok": False, "error": "task_id required for skip"}
        ops.set_control(skip_task_id=task_id)
        ops.telegram_notify(f"Autocode will SKIP {task_id} (UI)")
    elif action == "clear":
        ops.set_control(clear=True)
    elif action == "ping":
        sent = ops.telegram_notify(note or "Autocode UI ping OK")
        return {"ok": sent, "error": None if sent else "Telegram not configured", **snapshot()}
    else:
        return {"ok": False, "error": f"unknown action: {action}"}
    return {"ok": True, **snapshot()}



def _ollama_chat(message: str, system: str) -> str:
    """Call local Ollama chat API. Raises on transport/HTTP errors."""
    import json as _json
    import urllib.error
    import urllib.request

    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "coder-64k")
    body = _json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"http://{host}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read().decode())
    return (data.get("message") or {}).get("content") or data.get("response") or ""


def _should_escalate(message: str, local_reply: str) -> bool:
    text = f"{message}\n{local_reply}".lower()
    triggers = (
        "escalate:",
        "cannot",
        "can't",
        "too complex",
        "need a larger",
        "need cloud",
        "i am not able",
        "as a local model",
    )
    if any(t in text for t in triggers):
        return True
    keywords = ("architecture", "redesign", "migrate", "multi-service", "security audit")
    if len(message) > 400 or sum(1 for k in keywords if k in message.lower()) >= 2:
        return True
    if len(local_reply.strip()) < 40:
        return True
    return False


def _webhook_chat(url: str, token: str, payload: dict[str, Any], label: str) -> str:
    import json as _json
    import urllib.request

    headers = {"Content-Type": "application/json", "User-Agent": "Hawkeye/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=_json.dumps(payload).encode(),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=int(os.environ.get("AUTOCODE_DELEGATE_TIMEOUT_SEC", "120"))) as resp:
        raw = resp.read().decode()
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        return raw.strip() or f"({label} accepted; empty body)"
    if isinstance(data, dict):
        for key in ("reply", "message", "content", "text", "summary"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict) and isinstance(val.get("content"), str):
                return val["content"]
        return _json.dumps(data)[:2000]
    return str(data)


def _cloud_chat(message: str, local_reply: str, *, email: str | None = None) -> tuple[str, str]:
    """Escalate hard asks: Cursor → Grok Bot → API keys. Returns (reply, provider)."""
    import json as _json
    import urllib.request

    from ui import connections

    name = ui_auth.product_name()
    prompt = (
        f"You are {name}'s cloud escalator. The local Jetson model could not fully "
        "handle this operator instruction. Provide a concrete plan or answer, and if "
        "work should be queued, end with IMPROVE: <checklist item>.\n\n"
        f"Operator: {message}\n\nLocal model said:\n{local_reply[:2000]}"
    )
    payload = {
        "source": "hawkeye-ui-chat",
        "product": name,
        "message": message,
        "local_reply": local_reply[:4000],
        "prompt": prompt,
    }

    prefer = os.environ.get("AUTOCODE_CLOUD_PREFERENCE", "cursor").strip().lower()
    cursor_url = connections.resolve_secret("cursor", "webhook_url", email=email)
    grok_url = connections.resolve_secret("grok", "webhook_url", email=email)
    cursor_tok = connections.resolve_secret("cursor", "webhook_token", email=email) or connections.resolve_secret(
        "cursor", "api_key", email=email
    )
    grok_tok = connections.resolve_secret("grok", "webhook_token", email=email)
    order: list[tuple[str, str, str]] = []
    if prefer == "grok":
        if grok_url:
            order.append(("Grok Bot", grok_url, grok_tok))
        if cursor_url:
            order.append(("Cursor", cursor_url, cursor_tok))
    else:
        if cursor_url:
            order.append(("Cursor", cursor_url, cursor_tok))
        if grok_url:
            order.append(("Grok Bot", grok_url, grok_tok))

    errors: list[str] = []
    for label, url, token in order:
        try:
            return _webhook_chat(url, token, payload, label), label
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")

    anthropic = connections.resolve_secret("claude", "api_key", email=email)
    if anthropic:
        body = {
            "model": os.environ.get("AUTOCODE_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=_json.dumps(body).encode(),
            method="POST",
            headers={
                "x-api-key": anthropic,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode())
        parts = data.get("content") or []
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return text or "(empty Claude reply)", "Claude"
    openrouter = connections.resolve_secret("openrouter", "api_key", email=email)
    if openrouter:
        body = {
            "model": os.environ.get("AUTOCODE_OPENROUTER_MODEL", "x-ai/grok-2"),
            "messages": [
                {"role": "system", "content": f"You are {name} cloud escalator."},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=_json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {openrouter}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"], "OpenRouter"
    xai = connections.resolve_secret("grok", "api_key", email=email)
    if xai and not env_truthy("AUTOCODE_DISABLE_METERED_GROK", "1"):
        body = {
            "model": os.environ.get("AUTOCODE_GROK_MODEL", "grok-2-latest"),
            "messages": [
                {"role": "system", "content": f"You are {name} cloud escalator."},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=_json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {xai}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"], "Grok API"

    hint = (
        "No premium provider configured. Add Cursor / Grok / Claude under "
        "Account → Connections (recommended), or set machine .env webhooks. Local reply retained."
    )
    if errors:
        hint += " Webhook errors: " + "; ".join(errors)
    return hint, "none"


def _memory_context(message: str) -> tuple[str, list[dict[str, Any]]]:
    """Retrieve private SSD memory snippets for prompt injection."""
    if not env_truthy("HAWKEYE_MEMORY_ENABLED", "1"):
        return "", []
    try:
        from memory import get_store

        store = get_store()
        hits = store.search(message, limit=int(os.environ.get("HAWKEYE_MEMORY_TOP_K", "5") or "5"))
        prompt = store.format_for_prompt(message) if hits else ""
        return prompt, [
            {"id": h.id, "kind": h.kind, "score": round(h.score, 4), "text": h.text[:240]}
            for h in hits
        ]
    except Exception as e:  # noqa: BLE001
        print(f"[ui-chat] memory retrieve failed: {e}")
        return "", []


def _research_context(message: str) -> tuple[str, dict[str, Any] | None]:
    """Optional web research when the operator asks for facts/docs."""
    if not env_truthy("HAWKEYE_RESEARCH_ENABLED", "1"):
        return "", None
    try:
        from research import research, wants_research

        if not wants_research(message):
            return "", None
        result = research(
            message,
            limit=int(os.environ.get("HAWKEYE_RESEARCH_TOP_K", "5") or "5"),
        )
        return result.format_for_prompt(), result.to_dict()
    except Exception as e:  # noqa: BLE001
        print(f"[ui-chat] research failed: {e}")
        return "", {"error": str(e)}


def _persist_memory(
    message: str,
    local_reply: str,
    cloud_reply: str,
    *,
    provider: str,
    escalated: bool,
    research_payload: dict[str, Any] | None,
) -> str | None:
    if not env_truthy("HAWKEYE_MEMORY_ENABLED", "1"):
        return None
    try:
        from memory import get_store

        store = get_store()
        assistant = cloud_reply.strip() if (escalated and cloud_reply.strip()) else local_reply
        rec = store.remember_turn(
            message,
            assistant,
            provider=provider or ("cloud" if escalated else "local"),
            escalated=escalated,
            extra={"has_research": bool(research_payload and research_payload.get("sources"))},
        )
        if research_payload and research_payload.get("sources"):
            cite = "\n".join(
                f"- {s.get('title')}: {s.get('url')}"
                for s in research_payload["sources"][:5]
                if isinstance(s, dict)
            )
            store.remember(
                f"Research for: {message}\n{cite}",
                kind="research",
                meta={"provider": research_payload.get("provider")},
            )
        return rec.id if rec else None
    except Exception as e:  # noqa: BLE001
        print(f"[ui-chat] memory persist failed: {e}")
        return None


def handle_chat(message: str, seed_notion: bool = True, *, email: str | None = None) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "message required"}
    from ui import connections

    connections.set_request_user(email)
    stay_local = ui_auth.personal_local_only(email)
    name = ui_auth.product_name()
    memory_prompt, memory_hits = _memory_context(message)
    research_prompt, research_payload = _research_context(message)
    system = (
        f"You are {name} — BrownHawke's private assistant engineer / project manager "
        "running on a Jetson (free all-day local model). "
        "You research, remember, and drive other AIs/software to finish engineering work. "
        "Be concise. "
        "If the request is too strenuous for a local model, start with ESCALATE: and say why "
        "so Cursor or Grok Bot can take over. If a durable follow-up should be queued, "
        "end with IMPROVE: <checklist item> or BUG: <bug>. "
        "When web research is provided, cite the source URLs."
    )
    if memory_prompt:
        system += "\n\n" + memory_prompt
    if research_prompt:
        system += "\n\n" + research_prompt
    if stay_local:
        system += " PERSONAL_LOCAL_ONLY is on: do not ask for cloud models."
    local_reply = ""
    try:
        local_reply = _ollama_chat(message, system)
    except Exception as e:  # noqa: BLE001
        local_reply = f"(local model unavailable: {e})"
        escalated = True
    else:
        escalated = _should_escalate(message, local_reply)

    cloud_reply = ""
    provider = ""
    if escalated and stay_local:
        escalated = False
        provider = "local-only"
        if "(local model unavailable:" in local_reply:
            local_reply += "\n\n(PERSONAL_LOCAL_ONLY=1 — start Ollama or turn that flag off to use Cursor/Grok.)"
    elif escalated:
        try:
            # Cloud escalator also gets memory + research context.
            enriched = message
            if memory_prompt or research_prompt:
                enriched = (
                    f"{message}\n\n--- context ---\n{memory_prompt}\n{research_prompt}".strip()
                )
            cloud_reply, provider = _cloud_chat(enriched, local_reply, email=email)
        except Exception as e:  # noqa: BLE001
            cloud_reply = f"(cloud escalate failed: {e})"
            provider = "error"

    # Surface citations in the local reply when research ran and model omitted them.
    if research_payload and research_payload.get("sources") and not escalated:
        cite_block = ""
        try:
            from research.web import ResearchResult, ResearchSource

            sources = [
                ResearchSource(
                    title=str(s.get("title") or ""),
                    url=str(s.get("url") or ""),
                    snippet=str(s.get("snippet") or ""),
                    excerpt=str(s.get("excerpt") or ""),
                )
                for s in research_payload["sources"]
                if isinstance(s, dict)
            ]
            cite_block = ResearchResult(
                query=research_payload.get("query") or message,
                sources=sources,
                provider=str(research_payload.get("provider") or ""),
            ).format_for_chat()
        except Exception:  # noqa: BLE001
            cite_block = ""
        if cite_block and "http" not in local_reply.lower():
            local_reply = f"{local_reply.rstrip()}\n\n{cite_block}"

    seeded_task = None
    if seed_notion:
        blob = f"{message}\n{local_reply}\n{cloud_reply}"
        try:
            from orchestrator.self_feed import feed_from_agent_output, seed_checklist_item

            pages = feed_from_agent_output(blob, mock=False)
            if pages:
                seeded_task = pages[0]
            elif any(k in message.lower() for k in ("add to checklist", "queue", "ready task", "todo")):
                seeded_task = seed_checklist_item(
                    title=f"Operator: {message[:80]}",
                    acceptance=(
                        f"Queued from {name} UI chat.\n\n"
                        f"Operator request:\n{message}\n\n"
                        f"Local reply:\n{local_reply[:1000]}\n\n"
                        f"Cloud reply:\n{(cloud_reply or '')[:1000]}"
                    ),
                    kind="improve",
                    priority="P2",
                    mock=False,
                )
            elif (
                research_payload
                and research_payload.get("sources")
                and any(k in message.lower() for k in ("seed notion", "create task", "file a task"))
            ):
                urls = "\n".join(
                    f"- {s.get('url')}"
                    for s in research_payload["sources"][:5]
                    if isinstance(s, dict) and s.get("url")
                )
                seeded_task = seed_checklist_item(
                    title=f"Research follow-up: {message[:72]}",
                    acceptance=(
                        f"Seeded from {name} web research.\n\nQuery:\n{message}\n\nSources:\n{urls}"
                    ),
                    kind="improve",
                    priority="P2",
                    mock=False,
                )
        except Exception as e:  # noqa: BLE001
            print(f"[ui-chat] seed failed: {e}")

    memory_id = _persist_memory(
        message,
        local_reply,
        cloud_reply,
        provider=provider,
        escalated=escalated,
        research_payload=research_payload,
    )

    STATE.mkdir(parents=True, exist_ok=True)
    log = STATE / "ui-chat.jsonl"
    import json as _json
    import time as _time

    with log.open("a") as fh:
        fh.write(
            _json.dumps(
                {
                    "ts": _time.time(),
                    "message": message,
                    "local_reply": local_reply,
                    "escalated": escalated,
                    "cloud_reply": cloud_reply,
                    "provider": provider,
                    "local_only": stay_local,
                    "seeded_task": seeded_task,
                    "memory_id": memory_id,
                    "memory_hits": len(memory_hits),
                    "research": research_payload,
                }
            )
            + "\n"
        )
    return {
        "ok": True,
        "local_reply": local_reply,
        "escalated": escalated,
        "cloud_reply": cloud_reply,
        "provider": provider,
        "local_only": stay_local,
        "product": name,
        "seeded_task": seeded_task,
        "memory_id": memory_id,
        "memory_hits": memory_hits,
        "research": research_payload,
    }


def handle_list_boards() -> dict[str, Any]:
    from notion import pm as notion_pm
    from ui import connections

    boards = [b.to_dict() for b in notion_pm.list_boards()]
    return {
        "ok": True,
        "boards": boards,
        "projects": boards,
        "notion_connected": connections.has_secret("notion", "token"),
        "mock": env_truthy("HAWKEYE_PM_MOCK"),
    }


def handle_list_tasks(board_id: str, status: str | None, limit: int) -> dict[str, Any]:
    from notion import pm as notion_pm
    from ui import connections

    board_id = (board_id or "hawkeye").strip() or "hawkeye"
    token_present = connections.has_secret("notion", "token")
    force_mock = env_truthy("HAWKEYE_PM_MOCK")
    try:
        if force_mock or not token_present:
            data = notion_pm.mock_board_summary(board_id)
            if status and status.lower() not in ("all", "*", ""):
                data["tasks"] = [t for t in data["tasks"] if t.get("status") == status]
                data["total"] = len(data["tasks"])
            data["ok"] = True
            data["offline"] = not token_present
            return data
        data = notion_pm.board_summary(board_id)
        if status and status.lower() not in ("all", "*", ""):
            data["tasks"] = [t for t in data["tasks"] if t.get("status") == status]
            data["total"] = len(data["tasks"])
        data["ok"] = True
        return data
    except notion_pm.NotionError as e:
        data = notion_pm.mock_board_summary(board_id)
        data["ok"] = True
        data["warning"] = str(e)
        data["offline"] = True
        return data


def handle_get_task(page_id: str, board_id: str = "hawkeye") -> dict[str, Any]:
    from notion import pm as notion_pm

    try:
        if env_truthy("HAWKEYE_PM_MOCK") or page_id.startswith("mock-"):
            for t in notion_pm.mock_board_summary(board_id)["tasks"]:
                if t["page_id"] == page_id:
                    return {"ok": True, "task": t, "mock": True}
            return {"ok": False, "error": "task not found"}
        task = notion_pm.get_task(page_id, board_id=board_id)
        return {"ok": True, "task": task.to_dict()}
    except notion_pm.NotionError as e:
        return {"ok": False, "error": str(e)}


def handle_update_task_status(
    page_id: str, status: str, *, pr_url: str | None = None
) -> dict[str, Any]:
    from notion import pm as notion_pm

    try:
        if env_truthy("HAWKEYE_PM_MOCK") or page_id.startswith("mock-"):
            return {
                "ok": True,
                "mock": True,
                "task": {
                    "page_id": page_id,
                    "status": status,
                    "branch_pr": pr_url or "",
                },
            }
        task = notion_pm.update_task_status(page_id, status, pr_url=pr_url)
        return {"ok": True, "task": task.to_dict()}
    except notion_pm.NotionError as e:
        return {"ok": False, "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    server_version = "AutocodeUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[ui] {self.address_string()} {fmt % args}\n")

    def _send(
        self,
        code: int,
        body: bytes,
        content_type: str,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, val in extra_headers or []:
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def _read_raw(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_raw()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode() or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _ok_token(self, data: dict[str, Any] | None = None) -> bool:
        hdr = self.headers.get("X-Autocode-Token", "")
        tok = hdr or (data or {}).get("token") or ""
        return secrets.compare_digest(str(tok), TOKEN)

    def _current_user(self) -> str | None:
        """Signed-in email, or open-mode synthetic user for per-account settings."""
        token = self._session_token()
        user = ui_auth.session_user(token)
        if user:
            return user
        if not ui_auth.private_mode_enabled():
            return runtime.OPEN_USER
        return None

    def _session_token(self) -> str | None:
        return ui_auth.parse_session_cookie(self.headers.get("Cookie"))

    def _current_user(self) -> str | None:
        user = ui_auth.session_user(self._session_token())
        if user:
            return user
        if not ui_auth.private_mode_enabled():
            return "open@local"
        return None

    def _require_user(self) -> str | None:
        user = self._current_user()
        if user:
            return user
        self._send(*json_response({"ok": False, "error": "login required"}, 401))
        return None

    def _wants_secure_cookie(self) -> bool:
        if env_truthy("AUTOCODE_UI_SECURE"):
            return True
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        return proto == "https"

    def _authed(self) -> bool:
        return ui_auth.session_valid(self._session_token())

    def _require_session(self, path: str, *, html: bool = False) -> bool:
        """Return True if the request may proceed."""
        if not ui_auth.private_mode_enabled():
            return True
        if html and path in _PUBLIC_GET:
            return True
        if not html and path in _PUBLIC_POST:
            return True
        if path.startswith("/brand/"):
            return True
        if self._authed():
            return True
        if html:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return False
        self._send(*json_response({"ok": False, "error": "login required"}, 401))
        return False

    def _bind_request_user(self) -> None:
        try:
            from ui import connections

            user = self._current_user()
            if user and user != "open@local":
                connections.set_request_user(user)
            else:
                connections.set_request_user(None)
        except Exception:  # noqa: BLE001
            pass

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            if not self._require_session(path, html=True):
                return
            return self._static("index.html", "text/html; charset=utf-8")
        if path in ("/login", "/login.html"):
            if ui_auth.private_mode_enabled() and self._authed():
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            return self._static("login.html", "text/html; charset=utf-8")
        if path == "/app.css":
            return self._static("app.css", "text/css; charset=utf-8")
        if path == "/app.js":
            if not self._require_session(path, html=True):
                return
            return self._static("app.js", "application/javascript; charset=utf-8")
        if path.startswith("/brand/"):
            name = path.lstrip("/")
            ctype = (
                "image/jpeg"
                if name.endswith((".jpg", ".jpeg"))
                else "image/png"
                if name.endswith(".png")
                else "application/octet-stream"
            )
            return self._static(name, ctype)
        if path == "/api/auth":
            user = self._current_user() if self._authed() or not ui_auth.private_mode_enabled() else None
            profile = None
            if user and user != "open@local":
                try:
                    from ui import accounts

                    profile = accounts.get_profile(user)
                except Exception:  # noqa: BLE001
                    profile = None
            auth_user = None if (not user or user in ("open@local", runtime.OPEN_USER)) else user
            return self._send(
                *json_response(
                    {
                        "private_mode": ui_auth.private_mode_enabled(),
                        "credentials_ready": ui_auth.credentials_ready(),
                        "personal_local_only": ui_auth.personal_local_only(auth_user),
                        "product": ui_auth.product_name(),
                        "public_host": ui_auth.public_host(),
                        "allowed_email_domain": ui_auth.allowed_email_domain(),
                        "authed": self._authed(),
                        "user": auth_user,
                        "profile": profile,
                    }
                )
            )
        # Remaining API + pages need a session in private mode.
        if path.startswith("/api/"):
            if not self._require_session(path, html=False):
                return
        elif not self._require_session(path, html=True):
            return
        self._bind_request_user()
        if path == "/api/status":
            return self._send(*json_response(snapshot()))
        if path == "/api/ready":
            return self._send(*json_response(readiness(user=self._current_user())))
        if path == "/api/settings":
            return self._send(
                *json_response({"ok": True, **runtime.effective(self._current_user())})
            )
        if path == "/api/machine":
            user = self._require_user()
            if not user:
                return
            from ui import machine_settings

            return self._send(*json_response(machine_settings.status(user)))
        if path == "/api/me":
            user = self._require_user()
            if not user:
                return
            from ui import accounts

            return self._send(*json_response({"ok": True, "profile": accounts.get_profile(user)}))
        if path == "/api/users":
            user = self._require_user()
            if not user:
                return
            from ui import accounts

            return self._send(*json_response({"ok": True, "users": accounts.list_directory()}))
        if path == "/api/connections":
            user = self._require_user()
            if not user:
                return
            from ui import connections

            return self._send(*json_response(connections.list_connections(user)))
        if path == "/api/account/projects":
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            return self._send(*json_response(team_projects.list_projects(user)))
        if path.startswith("/api/account/projects/"):
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            pid = path.split("/api/account/projects/", 1)[1].strip("/")
            try:
                return self._send(*json_response(team_projects.get_project(user, pid)))
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 404))
        if path == "/api/messages/threads":
            user = self._require_user()
            if not user:
                return
            from ui import messages

            return self._send(*json_response(messages.list_threads(user)))
        if path.startswith("/api/messages/threads/"):
            user = self._require_user()
            if not user:
                return
            from ui import messages

            tid = path.split("/api/messages/threads/", 1)[1].strip("/")
            return self._send(*json_response(messages.get_thread(user, tid)))
        if path == "/api/logs":
            return self._send(*json_response(latest_log_tail()))
        if path == "/api/demo":
            return self._send(*json_response(demo_state()))
        if path == "/api/work":
            return self._send(*json_response(work_state()))
        if path == "/api/token":
            return self._send(*json_response({"token": TOKEN}))
        if path == "/api/memory":
            try:
                from memory import get_store

                return self._send(*json_response({"ok": True, **get_store().stats()}))
            except Exception as e:  # noqa: BLE001
                return self._send(*json_response({"ok": False, "error": str(e)}, 500))
        if path == "/api/mail":
            from urllib.parse import parse_qs

            from mail import list_messages

            qs = parse_qs(urlparse(self.path).query)
            status = (qs.get("status") or ["all"])[0]
            limit = int((qs.get("limit") or ["40"])[0] or 40)
            return self._send(*json_response(list_messages(limit=limit, status=status)))
        if path == "/api/projects" or path == "/api/boards":
            return self._send(*json_response(handle_list_boards()))
        if path == "/api/tasks":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query)
            board = (qs.get("board") or qs.get("project") or ["hawkeye"])[0]
            status = (qs.get("status") or ["all"])[0]
            limit = int((qs.get("limit") or ["50"])[0] or 50)
            return self._send(*json_response(handle_list_tasks(board, status, limit)))
        if path.startswith("/api/tasks/"):
            page_id = path.split("/api/tasks/", 1)[1].strip("/")
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query)
            board = (qs.get("board") or ["hawkeye"])[0]
            return self._send(*json_response(handle_get_task(page_id, board)))
        self._send(*json_response({"error": "not found"}, 404))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        # Resend inbound webhook — raw body required for signature verify.
        if path == "/api/webhooks/resend":
            if not env_truthy("HAWKEYE_MAIL_ENABLED"):
                return self._send(
                    *json_response({"ok": False, "error": "HAWKEYE_MAIL_ENABLED=0"}, 503)
                )
            raw = self._read_raw()
            headers = {k: v for k, v in self.headers.items()}
            try:
                from mail import handle_inbound_payload
                from mail.webhook import WebhookError

                out = handle_inbound_payload(raw, headers=headers)
                return self._send(*json_response(out))
            except WebhookError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
            except Exception as e:  # noqa: BLE001
                return self._send(*json_response({"ok": False, "error": str(e)}, 500))

        data = self._read_json()

        if path == "/api/login":
            if not ui_auth.private_mode_enabled():
                return self._send(
                    *json_response({"ok": True, "private_mode": False, "token": TOKEN})
                )
            if not ui_auth.credentials_ready():
                return self._send(
                    *json_response(
                        {
                            "ok": False,
                            "error": "No work users configured. "
                            "Add @brownhawke.engineering accounts via "
                            "python3 scripts/set_work_user.py --email …",
                        },
                        503,
                    )
                )
            email = str(data.get("email") or data.get("username") or "")
            sess = ui_auth.login(email, str(data.get("password") or ""))
            if not sess:
                return self._send(
                    *json_response(
                        {
                            "ok": False,
                            "error": f"Invalid email or password "
                            f"(only @{ui_auth.allowed_email_domain()} allowed)",
                        },
                        401,
                    )
                )
            # Optional first-time profile fields on login.
            if any(k in data for k in ("first_name", "last_name", "employee_number")):
                try:
                    from ui import accounts

                    accounts.update_profile(
                        ui_auth.session_user(sess) or email,
                        first_name=str(data.get("first_name") or "") or None,
                        last_name=str(data.get("last_name") or "") or None,
                        employee_number=str(data.get("employee_number") or "") or None,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[ui] profile update on login failed: {e}")
            profile = None
            try:
                from ui import accounts

                profile = accounts.get_profile(ui_auth.session_user(sess) or email)
            except Exception:  # noqa: BLE001
                profile = None
            return self._send(
                *json_response({"ok": True, "token": TOKEN, "profile": profile}),
                extra_headers=[
                    (
                        "Set-Cookie",
                        ui_auth.session_cookie_header(sess, secure=self._wants_secure_cookie()),
                    )
                ],
            )

        if path == "/api/logout":
            ui_auth.logout(self._session_token())
            return self._send(
                *json_response({"ok": True}),
                extra_headers=[("Set-Cookie", ui_auth.clear_session_cookie_header())],
            )

        if not self._require_session(path, html=False):
            return
        if not self._ok_token(data):
            return self._send(*json_response({"ok": False, "error": "bad token"}, 403))
        self._bind_request_user()
        if path == "/api/me":
            user = self._require_user()
            if not user:
                return
            from ui import accounts

            try:
                profile = accounts.update_profile(
                    user,
                    first_name=None if "first_name" not in data else str(data.get("first_name") or ""),
                    last_name=None if "last_name" not in data else str(data.get("last_name") or ""),
                    employee_number=None
                    if "employee_number" not in data
                    else str(data.get("employee_number") or ""),
                )
                return self._send(*json_response({"ok": True, "profile": profile}))
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/connections/"):
            user = self._require_user()
            if not user:
                return
            from ui import connections

            provider = path.split("/api/connections/", 1)[1].strip("/").lower()
            action = str(data.get("action") or "connect").lower()
            try:
                if action in ("disconnect", "delete", "revoke"):
                    out = connections.disconnect(user, provider)
                else:
                    secrets_in = data.get("secrets") if isinstance(data.get("secrets"), dict) else {}
                    # Also accept flat field names on the body.
                    for field in connections.PROVIDER_META.get(provider, {}).get("fields", []):
                        if field in data and field not in secrets_in:
                            secrets_in[field] = data.get(field)
                    out = connections.set_connection(
                        user,
                        provider,
                        secrets={k: str(v) for k, v in secrets_in.items()},
                        account_label=str(data.get("account_label") or "") or None,
                    )
                return self._send(*json_response(out))
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path == "/api/account/projects":
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            try:
                return self._send(
                    *json_response(
                        team_projects.create_project(
                            user,
                            name=str(data.get("name") or ""),
                            description=str(data.get("description") or ""),
                            notion_board_id=str(data.get("notion_board_id") or ""),
                        )
                    )
                )
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/account/projects/") and path.endswith("/share"):
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            pid = path[len("/api/account/projects/") : -len("/share")].strip("/")
            try:
                return self._send(
                    *json_response(
                        team_projects.share_project(
                            user,
                            pid,
                            member_email=str(data.get("email") or data.get("member_email") or ""),
                            role=str(data.get("role") or "editor"),
                        )
                    )
                )
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/account/projects/") and path.endswith("/unshare"):
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            pid = path[len("/api/account/projects/") : -len("/unshare")].strip("/")
            try:
                return self._send(
                    *json_response(
                        team_projects.unshare_project(
                            user,
                            pid,
                            str(data.get("email") or data.get("member_email") or ""),
                        )
                    )
                )
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/account/projects/") and (
            str(data.get("_method") or "").upper() == "DELETE"
            or str(data.get("action") or "").lower() == "delete"
        ):
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            pid = path.split("/api/account/projects/", 1)[1].strip("/")
            try:
                return self._send(*json_response(team_projects.delete_project(user, pid)))
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/account/projects/"):
            user = self._require_user()
            if not user:
                return
            from ui import team_projects

            pid = path.split("/api/account/projects/", 1)[1].strip("/")
            try:
                return self._send(
                    *json_response(
                        team_projects.update_project(
                            user,
                            pid,
                            name=None if "name" not in data else str(data.get("name") or ""),
                            description=None
                            if "description" not in data
                            else str(data.get("description") or ""),
                            notion_board_id=None
                            if "notion_board_id" not in data
                            else str(data.get("notion_board_id") or ""),
                        )
                    )
                )
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path == "/api/messages":
            user = self._require_user()
            if not user:
                return
            from ui import messages

            try:
                return self._send(
                    *json_response(
                        messages.send_message(
                            user,
                            str(data.get("to") or data.get("email") or ""),
                            str(data.get("body") or data.get("message") or ""),
                        )
                    )
                )
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path.startswith("/api/messages/threads/") and path.endswith("/read"):
            user = self._require_user()
            if not user:
                return
            from ui import messages

            tid = path[len("/api/messages/threads/") : -len("/read")].strip("/")
            return self._send(*json_response(messages.mark_thread_read(user, tid)))
        if path == "/api/machine":
            user = self._require_user()
            if not user:
                return
            from ui import machine_settings

            try:
                return self._send(*json_response(machine_settings.apply(user, data)))
            except PermissionError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 403))
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
        if path == "/api/control":
            return self._send(
                *json_response(
                    apply_control(
                        str(data.get("action") or ""),
                        str(data.get("note") or ""),
                        str(data.get("task_id") or ""),
                    )
                )
            )
        if path == "/api/settings":
            if "personal_local_only" not in data and "local_only" not in data:
                return self._send(
                    *json_response(
                        {"ok": False, "error": "pass personal_local_only (bool)"},
                        400,
                    )
                )
            user = self._current_user()
            if not user:
                return self._send(
                    *json_response({"ok": False, "error": "login required for settings"}, 401)
                )
            raw = data.get("personal_local_only", data.get("local_only"))
            if isinstance(raw, str):
                enabled = raw.lower() in ("1", "true", "yes", "on")
            else:
                enabled = bool(raw)
            try:
                out = runtime.set_personal_local_only(enabled, user=user)
            except ValueError as e:
                return self._send(*json_response({"ok": False, "error": str(e)}, 400))
            return self._send(*json_response({"ok": True, **out}))
        if path == "/api/demo":
            return self._send(*json_response(start_demo()))
        if path == "/api/work":
            force = str(data.get("force", "1")).lower() not in ("0", "false", "no")
            return self._send(*json_response(start_work_cycle(force=force)))

        if path == "/api/chat":
            user = self._current_user()
            email = user if user and user != "open@local" else None
            return self._send(
                *json_response(
                    handle_chat(
                        str(data.get("message") or ""),
                        seed_notion=str(data.get("seed_notion", "1")).lower()
                        not in ("0", "false", "no"),
                        email=email,
                    )
                )
            )
        if path == "/api/mail/inject":
            # Authenticated helper to drop a sample email into the inbox (no Resend).
            from mail import handle_inbound_payload

            return self._send(
                *json_response(
                    handle_inbound_payload(
                        json.dumps(
                            {
                                "from": data.get("from") or data.get("from_addr"),
                                "to": data.get("to") or data.get("to_addr"),
                                "subject": data.get("subject") or "",
                                "body": data.get("body") or "",
                            }
                        ),
                        skip_verify=True,
                    )
                )
            )
        if path.startswith("/api/mail/") and path.endswith("/draft"):
            from mail import draft_reply

            msg_id = path[len("/api/mail/") : -len("/draft")].strip("/")
            return self._send(*json_response(draft_reply(msg_id)))
        if path.startswith("/api/mail/") and path.endswith("/send"):
            from mail import send_reply

            msg_id = path[len("/api/mail/") : -len("/send")].strip("/")
            draft = data.get("draft")
            return self._send(
                *json_response(
                    send_reply(msg_id, draft=str(draft) if draft is not None else None)
                )
            )
        if path.startswith("/api/mail/") and path.endswith("/ignore"):
            from mail import ignore_message

            msg_id = path[len("/api/mail/") : -len("/ignore")].strip("/")
            return self._send(*json_response(ignore_message(msg_id)))
        if path.startswith("/api/tasks/") and (
            self.headers.get("X-HTTP-Method-Override", "").upper() == "PATCH"
            or str(data.get("_method") or "").upper() == "PATCH"
        ):
            page_id = path.split("/api/tasks/", 1)[1].strip("/")
            return self._send(
                *json_response(
                    handle_update_task_status(
                        page_id,
                        str(data.get("status") or ""),
                        pr_url=str(data.get("branch_pr") or data.get("pr_url") or "") or None,
                    )
                )
            )
        if path.startswith("/api/tasks/") and "status" in data:
            # Convenience POST {status} for browsers that avoid PATCH.
            page_id = path.split("/api/tasks/", 1)[1].strip("/")
            return self._send(
                *json_response(
                    handle_update_task_status(
                        page_id,
                        str(data.get("status") or ""),
                        pr_url=str(data.get("branch_pr") or data.get("pr_url") or "") or None,
                    )
                )
            )
        self._send(*json_response({"ok": False, "error": "not found"}, 404))

    def _static(self, name: str, content_type: str) -> None:
        path = STATIC / name
        if not path.is_file() or not path.resolve().is_relative_to(STATIC.resolve()):
            return self._send(*json_response({"error": f"missing {name}"}, 404))
        body = path.read_bytes()
        if name == "index.html":
            html = body.decode("utf-8").replace("{{TOKEN}}", TOKEN)
            html = html.replace("{{PRODUCT}}", ui_auth.product_name())
            body = html.encode("utf-8")
        elif name == "login.html":
            html = body.decode("utf-8").replace("{{PRODUCT}}", ui_auth.product_name())
            body = html.encode("utf-8")
        self._send(200, body, content_type)


def main() -> None:
    load_dotenv()
    STATE.mkdir(parents=True, exist_ok=True)
    name = ui_auth.product_name()
    mode = "private login" if ui_auth.private_mode_enabled() else "open (CSRF token only)"
    if ui_auth.personal_local_only():
        local = "local-only (cloud escalate disabled)"
    else:
        local = "local-first → Cursor/Grok escalate"
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{name} UI → http://{HOST}:{PORT}/  [{mode}; {local}]")
    if ui_auth.private_mode_enabled():
        print(f"Public host (tunnel): https://{ui_auth.public_host()}/")
    if ui_auth.private_mode_enabled() and not ui_auth.credentials_ready():
        print("WARNING: AUTOCODE_PRIVATE_MODE=1 but no work users configured.")
        print("         Run: python3 scripts/set_work_user.py --email you@brownhawke.engineering")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
