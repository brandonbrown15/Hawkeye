#!/usr/bin/env python3
"""Remote ops: status heartbeat + pause/abort/skip for Autocode.

Monitor / intervene without sitting at the Jetson:
  - state/status.json   — live heartbeat
  - state/control.json  — pause / abort / skip_task_id
  - python3 -m orchestrator.ops status|pause|resume|abort|skip|ping
  - optional Telegram progress pings

Recommended: Tailscale SSH → status/control. Notion is the cloud dashboard.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
STATUS_PATH = STATE / "status.json"
CONTROL_PATH = STATE / "control.json"


@dataclass
class NightStatus:
    phase: str = "idle"  # idle|starting|routing|running_local|escalating|paused|done|aborted
    task_id: str | None = None
    task_name: str | None = None
    route: str | None = None
    detail: str = ""
    started_at: str | None = None
    updated_at: str | None = None
    heartbeat_at: str | None = None
    night_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self) -> float | None:
        if not self.heartbeat_at:
            return None
        try:
            hb = datetime.fromisoformat(self.heartbeat_at.replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - hb).total_seconds())
        except ValueError:
            return None

    def looks_stuck(self, threshold_sec: int | None = None) -> bool:
        if self.phase not in ("running_local", "escalating", "routing"):
            return False
        thresh = threshold_sec or int(os.environ.get("AUTOCODE_STUCK_SECONDS", "900"))
        age = self.age_seconds()
        return age is not None and age >= thresh


@dataclass
class ControlFlags:
    paused: bool = False
    abort: bool = False
    skip_task_id: str | None = None
    note: str = ""
    updated_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else dict(default)
    except (json.JSONDecodeError, OSError):
        return dict(default)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def load_status() -> NightStatus:
    raw = _read_json(STATUS_PATH, {})
    known = set(NightStatus.__dataclass_fields__)
    kwargs = {k: v for k, v in raw.items() if k in known}
    return NightStatus(**kwargs)


def write_status(
    *,
    phase: str | None = None,
    task_id: str | None = None,
    task_name: str | None = None,
    route: str | None = None,
    detail: str | None = None,
    night_id: str | None = None,
    clear_task: bool = False,
    **extras: Any,
) -> NightStatus:
    cur = load_status()
    if phase is not None:
        cur.phase = phase
        if phase == "starting" and not cur.started_at:
            cur.started_at = _now()
    if clear_task:
        cur.task_id = None
        cur.task_name = None
        cur.route = None
    if task_id is not None:
        cur.task_id = task_id
    if task_name is not None:
        cur.task_name = task_name
    if route is not None:
        cur.route = route
    if detail is not None:
        cur.detail = detail
    if night_id is not None:
        cur.night_id = night_id
    if extras:
        cur.extras.update(extras)
    cur.updated_at = _now()
    cur.heartbeat_at = cur.updated_at
    _write_json(STATUS_PATH, asdict(cur))
    return cur


def heartbeat(detail: str | None = None) -> NightStatus:
    cur = load_status()
    if detail is not None:
        cur.detail = detail
    cur.heartbeat_at = _now()
    cur.updated_at = cur.heartbeat_at
    _write_json(STATUS_PATH, asdict(cur))
    return cur


def load_control() -> ControlFlags:
    raw = _read_json(CONTROL_PATH, {})
    return ControlFlags(
        paused=bool(raw.get("paused", False)),
        abort=bool(raw.get("abort", False)),
        skip_task_id=raw.get("skip_task_id") or None,
        note=str(raw.get("note") or ""),
        updated_at=raw.get("updated_at"),
    )


def set_control(
    *,
    paused: bool | None = None,
    abort: bool | None = None,
    skip_task_id: Any = ...,
    note: str | None = None,
    clear: bool = False,
) -> ControlFlags:
    if clear:
        flags = ControlFlags(updated_at=_now())
        _write_json(CONTROL_PATH, asdict(flags))
        return flags
    cur = load_control()
    if paused is not None:
        cur.paused = paused
    if abort is not None:
        cur.abort = abort
    if skip_task_id is not ...:
        cur.skip_task_id = skip_task_id
    if note is not None:
        cur.note = note
    cur.updated_at = _now()
    _write_json(CONTROL_PATH, asdict(cur))
    return cur


def wait_if_paused(poll_sec: float = 5.0) -> ControlFlags:
    """Block while paused; return latest flags. Abort still wins."""
    while True:
        flags = load_control()
        if flags.abort or not flags.paused:
            return flags
        write_status(phase="paused", detail=flags.note or "paused by operator")
        time.sleep(poll_sec)


def should_skip(task_id: str) -> bool:
    flags = load_control()
    return bool(flags.skip_task_id and flags.skip_task_id == task_id)


def clear_skip(task_id: str) -> None:
    flags = load_control()
    if flags.skip_task_id == task_id:
        set_control(skip_task_id=None)


def telegram_notify(text: str) -> bool:
    """Best-effort Telegram ping. Returns True if sent."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    if os.environ.get("AUTOCODE_TELEGRAM_PROGRESS", "1").lower() in ("0", "false", "no"):
        return False
    body = urllib.parse.urlencode(
        {"chat_id": chat, "text": text[:3500], "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001
        return False


def format_status(status: NightStatus | None = None, control: ControlFlags | None = None) -> str:
    status = status or load_status()
    control = control or load_control()
    age = status.age_seconds()
    age_s = f"{int(age)}s ago" if age is not None else "n/a"
    stuck = " YES" if status.looks_stuck() else " no"
    lines = [
        f"phase:      {status.phase}",
        f"task:       {status.task_id or '-'} {status.task_name or ''}".rstrip(),
        f"route:      {status.route or '-'}",
        f"detail:     {status.detail or '-'}",
        f"heartbeat:  {age_s}",
        f"stuck?:     {stuck}",
        f"paused:     {control.paused}",
        f"abort:      {control.abort}",
        f"skip:       {control.skip_task_id or '-'}",
        f"night_id:   {status.night_id or '-'}",
    ]
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Autocode remote ops status/control")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Print live status")
    p_set = sub.add_parser("pause", help="Pause between tasks / during waits")
    p_set.add_argument("--note", default="paused by operator")
    sub.add_parser("resume", help="Clear pause")
    sub.add_parser("abort", help="Abort the rest of the night after current step")
    p_skip = sub.add_parser("skip", help="Skip a task id when the loop reaches it")
    p_skip.add_argument("task_id")
    sub.add_parser("clear", help="Clear all control flags")
    p_ping = sub.add_parser("ping", help="Send a Telegram test ping")
    p_ping.add_argument("--text", default="Autocode ping OK")

    args = parser.parse_args()
    if args.cmd == "status":
        print(format_status())
        return
    if args.cmd == "pause":
        set_control(paused=True, note=args.note)
        telegram_notify(f"Autocode PAUSED: {args.note}")
        print(format_status())
        return
    if args.cmd == "resume":
        set_control(paused=False, note="")
        telegram_notify("Autocode RESUMED")
        print(format_status())
        return
    if args.cmd == "abort":
        set_control(abort=True, note="abort requested")
        telegram_notify("Autocode ABORT requested — stops after current step")
        print(format_status())
        return
    if args.cmd == "skip":
        set_control(skip_task_id=args.task_id)
        telegram_notify(f"Autocode will SKIP {args.task_id}")
        print(format_status())
        return
    if args.cmd == "clear":
        set_control(clear=True)
        print(format_status())
        return
    if args.cmd == "ping":
        ok = telegram_notify(args.text)
        print("sent" if ok else "Telegram not configured or send failed")
        return


if __name__ == "__main__":
    main()
