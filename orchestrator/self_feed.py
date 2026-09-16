#!/usr/bin/env python3
"""Self-feed Notion Build Queue from health, bugs, and improvement signals.

Autocode keeps programming from Notion until the project is finished. When it
spots health problems, failing checks, or IMPROVE:/BUG: suggestions, it adds
Ready checklist items so the next cycle picks them up without user input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
SEED_LOG = STATE / "self_feed.json"

IMPROVE_RE = re.compile(r"^\s*IMPROVE:\s*(.+)$", re.I | re.M)
BUG_RE = re.compile(r"^\s*BUG:\s*(.+)$", re.I | re.M)


def _env_truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _load_log() -> dict[str, Any]:
    STATE.mkdir(parents=True, exist_ok=True)
    if not SEED_LOG.exists():
        return {"seeds": {}, "last_health_at": 0.0}
    try:
        data = json.loads(SEED_LOG.read_text())
        return data if isinstance(data, dict) else {"seeds": {}, "last_health_at": 0.0}
    except (json.JSONDecodeError, OSError):
        return {"seeds": {}, "last_health_at": 0.0}


def _save_log(data: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    SEED_LOG.write_text(json.dumps(data, indent=2) + "\n")


def _fingerprint(kind: str, title: str) -> str:
    raw = f"{kind}:{title.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _already_seeded(fp: str, cooldown_sec: int) -> bool:
    row = _load_log().get("seeds", {}).get(fp)
    if not row:
        return False
    try:
        return (time.time() - float(row.get("ts", 0))) < cooldown_sec
    except (TypeError, ValueError):
        return False


def _mark_seeded(fp: str, title: str, page_id: str, kind: str) -> None:
    log = _load_log()
    seeds = log.setdefault("seeds", {})
    seeds[fp] = {
        "title": title,
        "page_id": page_id,
        "kind": kind,
        "ts": time.time(),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if len(seeds) > 200:
        oldest = sorted(seeds.items(), key=lambda kv: float(kv[1].get("ts", 0)))[
            : len(seeds) - 200
        ]
        for key, _ in oldest:
            seeds.pop(key, None)
    _save_log(log)


def ready_title_exists(title: str) -> bool:
    """Best-effort: True if a Ready task with the same name already exists."""
    try:
        from notion import client as notion

        body = {
            "filter": {
                "and": [
                    {"property": "Status", "select": {"equals": "Ready"}},
                    {"property": "Name", "title": {"equals": title[:100]}},
                ]
            },
            "page_size": 1,
        }
        result = notion.notion_request(
            "POST", f"/databases/{notion.db_id('build_queue')}/query", body
        )
        return bool(result.get("results"))
    except Exception:  # noqa: BLE001
        return False


def seed_checklist_item(
    *,
    title: str,
    acceptance: str,
    kind: str = "improve",
    repo: str = "",
    priority: str = "P2",
    complexity: str = "Local-safe",
    mock: bool = False,
) -> str | None:
    """Insert a Ready Notion task unless a recent duplicate exists."""
    if not _env_truthy("AUTOCODE_SELF_FEED_ENABLED", "1"):
        return None
    title = title.strip()[:120]
    if not title:
        return None
    cooldown = _env_int("AUTOCODE_SELF_FEED_COOLDOWN_SEC", 86400)
    fp = _fingerprint(kind, title)
    if _already_seeded(fp, cooldown):
        print(f"[self-feed] skip duplicate ({kind}): {title}")
        return None
    if not mock and ready_title_exists(title):
        print(f"[self-feed] skip existing Ready: {title}")
        _mark_seeded(fp, title, "existing", kind)
        return None
    if mock:
        page_id = f"mock-seed-{fp}"
        _mark_seeded(fp, title, page_id, kind)
        print(f"[self-feed:mock] {kind}: {title}")
        return page_id
    try:
        from notion import client as notion

        page_id = notion.seed_ready_task(
            name=title,
            acceptance=acceptance,
            repo=repo,
            priority=priority,
            complexity=complexity,
            model_route="Local Hermes",
        )
        _mark_seeded(fp, title, page_id, kind)
        print(f"[self-feed] seeded {kind} → {page_id}: {title}")
        return page_id
    except Exception as e:  # noqa: BLE001
        print(f"[self-feed] failed to seed {title!r}: {e}")
        return None


def parse_improve_signals(text: str) -> list[tuple[str, str]]:
    """Return (kind, idea) pairs from IMPROVE:/BUG: lines."""
    found: list[tuple[str, str]] = []
    for m in IMPROVE_RE.finditer(text or ""):
        found.append(("improve", m.group(1).strip()))
    for m in BUG_RE.finditer(text or ""):
        found.append(("bug", m.group(1).strip()))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, item in found:
        key = f"{kind}:{item.lower()}"
        if item and key not in seen:
            seen.add(key)
            out.append((kind, item))
    return out[:8]


def feed_from_agent_output(
    text: str,
    *,
    repo: str = "",
    mock: bool = False,
) -> list[str]:
    """Seed Ready tasks from IMPROVE:/BUG: lines in agent output."""
    seeded: list[str] = []
    for kind, idea in parse_improve_signals(text):
        title = f"{'Bug' if kind == 'bug' else 'Improve'}: {idea}"
        page = seed_checklist_item(
            title=title[:120],
            acceptance=(
                "Autocode self-feed spotted this during a coding turn.\n\n"
                f"Do: {idea}\n\n"
                "Open a small PR. Do not expand scope. Run available checks."
            ),
            kind=kind,
            repo=repo,
            priority="P1" if kind == "bug" else "P2",
            mock=mock,
        )
        if page:
            seeded.append(page)
    return seeded


def feed_from_check_failure(
    summary: str,
    *,
    repo: str = "",
    task_name: str = "",
    mock: bool = False,
) -> str | None:
    snippet = (summary or "checks failed").strip().splitlines()[0][:80]
    title = f"Fix: checks failed — {task_name or repo or snippet}"[:120]
    return seed_checklist_item(
        title=title,
        acceptance=(
            "Repo checks failed during an Autocode run.\n\n"
            f"Context:\n{summary[:1500]}\n\n"
            "Reproduce locally, fix the failure, open a PR. Stay minimal."
        ),
        kind="bug",
        repo=repo,
        priority="P1",
        mock=mock,
    )


def maybe_seed_routine_health(*, mock: bool = False, force: bool = False) -> list[str]:
    """Periodically seed health / bug-check tasks from local stack status."""
    if not _env_truthy("AUTOCODE_HEALTH_FEED_ENABLED", "1"):
        return []
    interval = _env_int("AUTOCODE_HEALTH_FEED_INTERVAL_SEC", 21600)  # 6h
    log = _load_log()
    last = float(log.get("last_health_at") or 0)
    if not force and (time.time() - last) < interval:
        return []

    seeded: list[str] = []
    try:
        from orchestrator.health import check_local_stack

        report = check_local_stack()
        details = "; ".join(report.details)
        if not report.local_ready:
            page = seed_checklist_item(
                title="Health: restore local Hermes/Ollama stack",
                acceptance=(
                    "Local coding stack is not ready.\n\n"
                    f"Doctor details: {details}\n\n"
                    "Fix Hermes CLI + Ollama model so Autocode can keep coding locally. "
                    "Document what changed."
                ),
                kind="health",
                priority="P0",
                complexity="Local-safe",
                mock=mock,
            )
            if page:
                seeded.append(page)
        else:
            page = seed_checklist_item(
                title="Health: routine project bug and smoke check",
                acceptance=(
                    "Routine Autocode health pass.\n\n"
                    "1) Run available tests/linters in WORKSPACE_REPOS.\n"
                    "2) Fix any clear bugs or brittle failures you can verify.\n"
                    "3) If you spot a worthwhile improvement, add an IMPROVE: line "
                    "so Autocode can enqueue it.\n"
                    "4) Open a small PR only if you made a real fix; otherwise leave a short note."
                ),
                kind="health",
                priority="P3",
                mock=mock,
            )
            if page:
                seeded.append(page)
    except Exception as e:  # noqa: BLE001
        print(f"[self-feed] health probe failed: {e}")

    log = _load_log()
    log["last_health_at"] = time.time()
    _save_log(log)
    return seeded


def main() -> None:
    parser = argparse.ArgumentParser(description="Autocode Notion self-feed")
    parser.add_argument("--health", action="store_true", help="Run routine health/bug seed")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--from-text", help="Parse IMPROVE:/BUG: lines from a file and seed")
    args = parser.parse_args()
    if args.from_text:
        text = Path(args.from_text).read_text()
        print(feed_from_agent_output(text, mock=args.mock))
    if args.health or not args.from_text:
        print(maybe_seed_routine_health(mock=args.mock, force=args.force or not args.from_text))


if __name__ == "__main__":
    main()


