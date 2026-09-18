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
    }
)


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


def update_status() -> dict[str, Any]:
    ok_check, check_out = False, ""
    script = ROOT / "scripts" / "hawkeye_self_update.sh"
    if script.is_file():
        try:
            proc = subprocess.run(
                ["bash", str(script), "--check"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(ROOT),
                check=False,
            )
            ok_check = proc.returncode == 0
            check_out = (proc.stdout or proc.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            check_out = str(e)
    timer_ok, timer_out = _systemctl_user("is-active", "hawkeye-update.timer")
    ui_ok, _ = _systemctl_user("is-active", "hawkeye-ui.service")
    tunnel_ok, _ = _systemctl_user("is-active", "hawkeye-tunnel.service")
    branch = os.environ.get("HAWKEYE_UPDATE_BRANCH", "").strip() or "main"
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
        "script_present": script.is_file(),
    }


def status(email: str | None = None) -> dict[str, Any]:
    env = _read_env_file()
    tunnel = bool(os.environ.get("TUNNEL_TOKEN", "").strip() or env.get("TUNNEL_TOKEN"))
    mem = bool(os.environ.get("HAWKEYE_MEMORY_KEY", "").strip() or env.get("HAWKEYE_MEMORY_KEY"))
    secrets = bool(os.environ.get("HAWKEYE_SECRETS_KEY", "").strip() or env.get("HAWKEYE_SECRETS_KEY"))
    return {
        "ok": True,
        "admin": is_admin(email),
        "public_host": ui_auth.public_host(),
        "tunnel_token_set": tunnel,
        "memory_key_set": mem,
        "secrets_key_set": secrets or mem,
        "encryption_ready": mem or secrets,
        "autostart": update_status(),
        "hint": (
            "Add Cloudflare Tunnel install token, encryption key, and auto-update "
            "branch here. Per-user API keys live under Connections."
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
            env_updates["AUTOCODE_PUBLIC_HOST"] = host
            actions.append("public_host")

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

    force_update = str(updates.get("force_update") or "").lower() in ("1", "true", "yes")
    if force_update:
        script = ROOT / "scripts" / "hawkeye_self_update.sh"
        if not script.is_file():
            raise ValueError("hawkeye_self_update.sh missing — pull auto-update scripts first")
        try:
            proc = subprocess.run(
                ["bash", str(script), "--force"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            actions.append(
                "force_update_ok" if proc.returncode == 0 else f"force_update_fail:{proc.returncode}"
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ValueError(f"force update failed: {e}") from e

    out = status(email)
    out["applied"] = actions
    out["updated_at"] = time.time()
    return out
