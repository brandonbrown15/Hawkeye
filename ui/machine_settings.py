"""Machine-wide Jetson settings editable from the Hawkeye UI.

Used for secrets that are box-level (not per coworker): Cloudflare tunnel
install token, auto-update branch/toggle, and encryption key bootstrap.
Values persist into the checkout `.env` so systemd units pick them up.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ui import auth as ui_auth

_LOCK = threading.RLock()
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

# Keys operators may set from Account → Machine (never returned in plaintext after save
# except for non-secret flags like branch / enabled).
SECRET_KEYS = frozenset(
    {
        "TUNNEL_TOKEN",
        "HAWKEYE_MEMORY_KEY",
        "HAWKEYE_SECRETS_KEY",
    }
)
PUBLIC_KEYS = frozenset(
    {
        "HAWKEYE_UPDATE_ENABLED",
        "HAWKEYE_UPDATE_BRANCH",
        "HAWKEYE_UPDATE_REMOTE",
        "AUTOCODE_PUBLIC_HOST",
        "NOTION_HUB_PAGE",
        "NOTION_BUILD_QUEUE_DB",
    }
)

_NOTION_ID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")


def admin_emails() -> set[str]:
    """Emails allowed to change Jetson-wide Machine settings.

    Default is Brandon only. Set HAWKEYE_ADMIN_EMAILS (comma-separated) to
    extend or replace. An explicit empty value denies everyone.
    """
    raw = os.environ.get("HAWKEYE_ADMIN_EMAILS")
    if raw is not None:
        return {ui_auth.normalize_email(x) for x in raw.split(",") if x.strip()}
    return {"brandon@brownhawke.engineering"}


def is_admin(email: str | None) -> bool:
    if not email:
        return False
    email = ui_auth.normalize_email(email)
    return email in admin_emails()


def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.is_file():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            out[key] = val
    return out


def _write_env_updates(updates: dict[str, str]) -> None:
    """Upsert KEY=value lines in .env without wiping comments."""
    with _LOCK:
        existing_lines: list[str] = []
        if ENV_PATH.is_file():
            existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        keys_done: set[str] = set()
        new_lines: list[str] = []
        for line in existing_lines:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
            if m and m.group(1) in updates:
                key = m.group(1)
                new_lines.append(f"{key}={updates[key]}")
                keys_done.add(key)
            else:
                new_lines.append(line)
        for key, val in updates.items():
            if key not in keys_done:
                new_lines.append(f"{key}={val}")
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(new_lines).rstrip() + "\n"
        ENV_PATH.write_text(text, encoding="utf-8")
        # Apply to current process so the running UI sees changes immediately.
        for key, val in updates.items():
            os.environ[key] = val


def _systemctl_user(*args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _normalize_notion_id(raw: str) -> str:
    """Accept URL or bare UUID; return hyphenless/hyphenated id as pasted (trimmed)."""
    s = (raw or "").strip()
    if not s:
        return ""
    # Notion URLs end with 32 hex chars (optionally hyphenated UUID).
    m = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", s)
    if m:
        return m.group(1)
    if _NOTION_ID_RE.match(s):
        return s
    raise ValueError("Notion id must be a page/database UUID (or Notion URL containing one)")


def sync_github_token_from_connections(email: str | None = None) -> bool:
    """Copy Connections GitHub PAT into process + .env so self-update / timer can fetch.

    Vault-only tokens never reach hawkeye-update.service (EnvironmentFile=.env).
    Returns True when a token is available in the environment afterward.
    """
    from ui import connections

    token = connections.resolve_secret("github", "token", email=email).strip()
    if not token:
        token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if not token:
            token = (_read_env_file().get("GITHUB_TOKEN") or _read_env_file().get("GH_TOKEN") or "").strip()
    if not token:
        return False
    env = _read_env_file()
    existing = (os.environ.get("GITHUB_TOKEN") or env.get("GITHUB_TOKEN") or "").strip()
    if existing != token:
        _write_env_updates({"GITHUB_TOKEN": token})
    else:
        os.environ["GITHUB_TOKEN"] = token
    return True


def _self_update_env(email: str | None = None) -> dict[str, str]:
    """Env for hawkeye_self_update.sh with GITHUB_TOKEN injected when available."""
    sync_github_token_from_connections(email)
    env = dict(os.environ)
    token = (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip()
    if token:
        env["GITHUB_TOKEN"] = token
        env["GH_TOKEN"] = token
    return env


def repair_git_https_fetch(email: str | None = None) -> dict[str, Any]:
    """Rewrite origin to HTTPS + PAT auth so fetch works without SSH keys.

    Safe to call repeatedly. Used by Force update before hawkeye_self_update.sh
    so Jetsons stuck on SSH-only remotes can unlock over the Cloudflare tunnel UI.
    """
    sync_github_token_from_connections(email)
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        token = (_read_env_file().get("GITHUB_TOKEN") or _read_env_file().get("GH_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "no GITHUB_TOKEN — save Account → Connections → GitHub first"}

    remote = os.environ.get("HAWKEYE_UPDATE_REMOTE", "origin").strip() or "origin"
    steps: list[str] = []
    try:
        url_proc = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        url = (url_proc.stdout or "").strip()
        repo = "brandonbrown15/Hawkeye"
        m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)(?:\.git)?", url)
        if m:
            repo = f"{m.group(1)}/{m.group(2)}"
        https = f"https://github.com/{repo}.git"
        set_url = subprocess.run(
            ["git", "remote", "set-url", remote, https],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if set_url.returncode != 0:
            return {
                "ok": False,
                "error": (set_url.stderr or set_url.stdout or "git remote set-url failed").strip()[:300],
                "steps": steps,
            }
        steps.append(f"remote={https}")

        import base64

        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode().strip()
        hdr = subprocess.run(
            ["git", "config", "--local", "http.https://github.com/.extraheader", f"AUTHORIZATION: basic {basic}"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if hdr.returncode != 0:
            return {
                "ok": False,
                "error": (hdr.stderr or "git config extraheader failed").strip()[:300],
                "steps": steps,
            }
        steps.append("extraheader=ok")

        branch = os.environ.get("HAWKEYE_UPDATE_BRANCH", "main").strip() or "main"
        fetch = subprocess.run(
            ["git", "fetch", "--quiet", remote, branch],
            cwd=str(ROOT),
            env=_self_update_env(email),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if fetch.returncode != 0:
            err = (fetch.stderr or fetch.stdout or "git fetch failed").strip()[:400]
            return {"ok": False, "error": err, "steps": steps}
        steps.append(f"fetch={remote}/{branch}")
        return {"ok": True, "repo": repo, "steps": steps}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e), "steps": steps}


def _run_self_update(*args: str, email: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    script = ROOT / "scripts" / "hawkeye_self_update.sh"
    if not script.is_file():
        raise FileNotFoundError("hawkeye_self_update.sh missing — pull auto-update scripts first")
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(ROOT),
        env=_self_update_env(email),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _ollama_reachable() -> bool:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").strip() or "127.0.0.1:11434"
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://{host}/api/tags", timeout=3) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except Exception:  # noqa: BLE001
        return False


def ensure_ollama(*, restart: bool = False, timeout_sec: int = 120) -> dict[str, Any]:
    """Start (or restart) the local Ollama daemon via ensure_ollama.sh."""
    script = ROOT / "ollama" / "ensure_ollama.sh"
    if not script.is_file():
        return {"ok": False, "error": "ollama/ensure_ollama.sh missing", "reachable": False}
    cmd = ["bash", str(script)]
    if restart:
        cmd.append("--restart")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        reachable = _ollama_reachable()
        return {
            "ok": proc.returncode == 0 and reachable,
            "reachable": reachable,
            "returncode": proc.returncode,
            "log": out[-4000:],
        }
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e), "reachable": _ollama_reachable()}


def update_status(email: str | None = None) -> dict[str, Any]:
    ok_check, check_out = False, ""
    script = ROOT / "scripts" / "hawkeye_self_update.sh"
    if script.is_file():
        try:
            proc = _run_self_update("--check", email=email, timeout=60)
            ok_check = proc.returncode == 0
            check_out = (proc.stdout or proc.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            check_out = str(e)
    timer_ok, timer_out = _systemctl_user("is-active", "hawkeye-update.timer")
    ui_ok, _ = _systemctl_user("is-active", "hawkeye-ui.service")
    tunnel_ok, _ = _systemctl_user("is-active", "hawkeye-tunnel.service")
    branch = os.environ.get("HAWKEYE_UPDATE_BRANCH", "").strip() or "main"
    ollama_ok = _ollama_reachable()
    github_token_ready = bool(
        (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        or (_read_env_file().get("GITHUB_TOKEN") or _read_env_file().get("GH_TOKEN") or "").strip()
    )
    return {
        "update_enabled": os.environ.get("HAWKEYE_UPDATE_ENABLED", "1").strip() != "0",
        "update_branch": branch,
        "update_remote": os.environ.get("HAWKEYE_UPDATE_REMOTE", "origin").strip() or "origin",
        "update_check": check_out,
        "update_check_ok": ok_check,
        "timer_active": timer_ok,
        "timer_detail": timer_out,
        "ui_active": ui_ok,
        "tunnel_active": tunnel_ok,
        "ollama_active": ollama_ok,
        "script_present": script.is_file(),
        "github_token_ready": github_token_ready,
    }


def status(email: str | None = None) -> dict[str, Any]:
    env = _read_env_file()
    tunnel = bool(os.environ.get("TUNNEL_TOKEN", "").strip() or env.get("TUNNEL_TOKEN"))
    mem = bool(os.environ.get("HAWKEYE_MEMORY_KEY", "").strip() or env.get("HAWKEYE_MEMORY_KEY"))
    secrets = bool(os.environ.get("HAWKEYE_SECRETS_KEY", "").strip() or env.get("HAWKEYE_SECRETS_KEY"))
    hub = (os.environ.get("NOTION_HUB_PAGE") or env.get("NOTION_HUB_PAGE") or "").strip()
    bq = (os.environ.get("NOTION_BUILD_QUEUE_DB") or env.get("NOTION_BUILD_QUEUE_DB") or "").strip()
    return {
        "ok": True,
        "admin": is_admin(email),
        "public_host": ui_auth.public_host(),
        "tunnel_token_set": tunnel,
        "memory_key_set": mem,
        "secrets_key_set": secrets or mem,
        "encryption_ready": mem or secrets,
        "notion_hub_page": hub,
        "notion_hub_page_set": bool(hub),
        "notion_build_queue_db": bq,
        "notion_build_queue_set": bool(bq),
        "autostart": update_status(email),
        "hint": (
            "Add Cloudflare Tunnel install token, encryption key, Notion hub page id, "
            "and auto-update branch here. Use Wake Ollama if chat says connection refused. "
            "Force update injects Connections → GitHub token for HTTPS fetch. "
            "Per-user API keys live under Connections."
        ),
    }


def apply(email: str, updates: dict[str, Any]) -> dict[str, Any]:
    if not is_admin(email):
        raise PermissionError("only Hawkeye admins can change machine settings")
    env_updates: dict[str, str] = {}
    actions: list[str] = []

    if "tunnel_token" in updates and updates["tunnel_token"] is not None:
        tok = str(updates["tunnel_token"]).strip()
        if tok:
            env_updates["TUNNEL_TOKEN"] = tok
            actions.append("tunnel_token")

    if "memory_key" in updates and updates["memory_key"] is not None:
        key = str(updates["memory_key"]).strip()
        if key:
            # Do not overwrite an existing key unless force_memory_key=1.
            existing = os.environ.get("HAWKEYE_MEMORY_KEY", "").strip() or _read_env_file().get(
                "HAWKEYE_MEMORY_KEY", ""
            )
            force = str(updates.get("force_memory_key") or "").lower() in ("1", "true", "yes")
            if existing and not force:
                raise ValueError(
                    "HAWKEYE_MEMORY_KEY already set — pass force_memory_key=1 to rotate "
                    "(will invalidate previously encrypted secrets/memory)"
                )
            env_updates["HAWKEYE_MEMORY_KEY"] = key
            actions.append("memory_key")

    if "update_enabled" in updates and updates["update_enabled"] is not None:
        on = str(updates["update_enabled"]).lower() not in ("0", "false", "no", "off")
        env_updates["HAWKEYE_UPDATE_ENABLED"] = "1" if on else "0"
        actions.append("update_enabled")

    if "update_branch" in updates and updates["update_branch"] is not None:
        branch = str(updates["update_branch"]).strip()
        if branch and not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
            raise ValueError("invalid update branch name")
        if branch:
            env_updates["HAWKEYE_UPDATE_BRANCH"] = branch
            actions.append("update_branch")

    if "public_host" in updates and updates["public_host"] is not None:
        host = str(updates["public_host"]).strip()
        if host:
            # Keep hostname single-line (reject shell/env injection leftovers).
            host = host.split("\n", 1)[0].split(";", 1)[0].strip()
            if host:
                env_updates["AUTOCODE_PUBLIC_HOST"] = host
                actions.append("public_host")

    if "github_token" in updates and updates["github_token"] is not None:
        tok = str(updates["github_token"]).strip()
        if tok:
            env_updates["GITHUB_TOKEN"] = tok
            actions.append("github_token")

    if "notion_hub_page" in updates and updates["notion_hub_page"] is not None:
        hub = str(updates["notion_hub_page"]).strip()
        if hub:
            env_updates["NOTION_HUB_PAGE"] = _normalize_notion_id(hub)
            actions.append("notion_hub_page")

    if "notion_build_queue_db" in updates and updates["notion_build_queue_db"] is not None:
        bq = str(updates["notion_build_queue_db"]).strip()
        if bq:
            env_updates["NOTION_BUILD_QUEUE_DB"] = _normalize_notion_id(bq)
            actions.append("notion_build_queue_db")

    if env_updates:
        _write_env_updates(env_updates)

    restart_tunnel = str(updates.get("restart_tunnel") or "").lower() in ("1", "true", "yes")
    if "tunnel_token" in actions or restart_tunnel:
        # Re-run autostart so tunnel unit picks up TUNNEL_TOKEN.
        installer = ROOT / "scripts" / "install_hawkeye_autostart.sh"
        if installer.is_file():
            try:
                subprocess.run(
                    ["bash", str(installer)],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                actions.append("reinstall_autostart")
            except (OSError, subprocess.TimeoutExpired) as e:
                actions.append(f"autostart_failed:{e}")
        ok, detail = _systemctl_user("restart", "hawkeye-tunnel.service")
        actions.append("tunnel_restart_ok" if ok else f"tunnel_restart_fail:{detail[:120]}")

    # Keep .env GITHUB_TOKEN aligned with Connections so the 5-min timer can HTTPS-fetch.
    if sync_github_token_from_connections(email):
        actions.append("github_token_synced")

    provision_notion = str(updates.get("provision_notion") or "").lower() in ("1", "true", "yes")
    provision_log = ""
    if provision_notion:
        from ui import connections

        hub = (os.environ.get("NOTION_HUB_PAGE") or _read_env_file().get("NOTION_HUB_PAGE") or "").strip()
        if not hub:
            raise ValueError("Set Notion hub page id first (Account → Machine)")
        token = connections.resolve_secret("notion", "token", email=email).strip()
        if not token:
            raise ValueError("Connect Notion under Account → Connections first")
        script = ROOT / "notion" / "client.py"
        if not script.is_file():
            raise ValueError("notion/client.py missing")
        env = dict(os.environ)
        env["NOTION_TOKEN"] = token
        env["NOTION_HUB_PAGE"] = hub
        try:
            proc = subprocess.run(
                ["python3", str(script), "provision", "--seed", "--parent", hub],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            provision_log = ((proc.stdout or "") + (proc.stderr or "")).strip()[-4000:]
            actions.append(
                "provision_notion_ok" if proc.returncode == 0 else f"provision_notion_fail:{proc.returncode}"
            )
            if proc.returncode != 0:
                raise ValueError(f"Notion provision failed: {provision_log[-500:] or proc.returncode}")
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ValueError(f"Notion provision failed: {e}") from e

    force_update = str(updates.get("force_update") or "").lower() in ("1", "true", "yes")
    repair_git = str(updates.get("repair_git") or "").lower() in ("1", "true", "yes")
    force_log = ""
    repair_result: dict[str, Any] | None = None
    if force_update or repair_git:
        repair_result = repair_git_https_fetch(email)
        actions.append("repair_git_ok" if repair_result.get("ok") else f"repair_git_fail:{repair_result.get('error', '')[:80]}")
        if repair_git and not force_update and not repair_result.get("ok"):
            raise ValueError(f"git repair failed: {repair_result.get('error')}")
    if force_update:
        try:
            proc = _run_self_update("--force", email=email, timeout=600)
            force_log = ((proc.stdout or "") + (proc.stderr or "")).strip()[-4000:]
            actions.append(
                "force_update_ok" if proc.returncode == 0 else f"force_update_fail:{proc.returncode}"
            )
            if proc.returncode != 0:
                raise ValueError(
                    f"force update failed ({proc.returncode}): "
                    f"{force_log[-400:] or 'see logs/self-update.log'}"
                )
        except FileNotFoundError as e:
            raise ValueError(str(e)) from e
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ValueError(f"force update failed: {e}") from e

    wake_ollama = str(updates.get("wake_ollama") or "").lower() in ("1", "true", "yes")
    restart_ollama = str(updates.get("restart_ollama") or "").lower() in ("1", "true", "yes")
    ollama_result: dict[str, Any] | None = None
    if wake_ollama or restart_ollama:
        ollama_result = ensure_ollama(restart=restart_ollama)
        actions.append(
            "wake_ollama_ok" if ollama_result.get("ok") else f"wake_ollama_fail:{ollama_result.get('error') or ollama_result.get('returncode')}"
        )

    out = status(email)
    out["applied"] = actions
    out["updated_at"] = time.time()
    if ollama_result is not None:
        out["ollama"] = ollama_result
    if force_log:
        out["force_update_log"] = force_log
    if repair_result is not None:
        out["repair_git"] = repair_result
    if provision_log:
        out["provision_notion_log"] = provision_log
    return out