"""Chat-layer project management: parse operator intents and talk to Notion.

Deterministic — does not call Ollama or Cursor. Cursor escalate stays on the
normal chat path when this module returns None.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from notion import pm as notion_pm

_BOARD_ALIASES = {
    "hawkeye": "hawkeye",
    "hk": "hawkeye",
    "rose": "rose",
    "autocode": "autocode",
    "lcm": "autocode",
}

_CREATE_RE = re.compile(
    r"^(?:please\s+)?(?:add|create|queue|file)\s+(?:an?\s+)?"
    r"(?:(?P<priority>p[0-3])\s+)?ready\s+task\s*[:\-–]\s*(?P<title>.+)$",
    re.I,
)
_UPDATE_RE = re.compile(
    r"^(?:please\s+)?(?:mark|set|move)\s+"
    r"(?P<task_id>[A-Za-z]{1,8}-?\d{1,6})\s+"
    r"(?:as|to)?\s*(?P<status>.+)$",
    re.I,
)
_LIST_ON_BOARD_RE = re.compile(
    r"^(?:what(?:'s|s| is)\s+on|show|list)\s+"
    r"(?:the\s+)?(?:(?P<board>hawkeye|hk|rose|autocode|lcm)\s+)?"
    r"(?:build\s+)?board\s*\??$",
    re.I,
)
_LIST_TASKS_RE = re.compile(
    r"^(?:show|list)\s+(?:the\s+)?(?:all\s+)?"
    r"(?:(?P<board>hawkeye|hk|rose|autocode|lcm)\s+)?(?:board\s+)?tasks\s*\??$",
    re.I,
)
_LIST_OPEN_PRIO_RE = re.compile(
    r"^(?:show|list|what(?:'s|s| is))\s+"
    r"(?:the\s+)?open(?:\s+tasks?)?"
    r"(?P<prios>(?:\s+p[0-3](?:\s*(?:/|,|and)\s*p[0-3])*)+)?"
    r"(?:\s+tasks?)?\s*\??$",
    re.I,
)
_PRIO_RE = re.compile(r"p[0-3]", re.I)
_ALL_RE = re.compile(r"\b(?:all|everything|entire)\b", re.I)


@dataclass
class PmIntent:
    action: str  # list | update | create
    board_id: str = "hawkeye"
    task_id: str = ""
    status: str | None = None
    priorities: list[str] = field(default_factory=list)
    open_only: bool = True
    title: str = ""
    priority: str = "P2"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def _board_from_alias(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    return _BOARD_ALIASES.get(key, "hawkeye")


def _priorities_in(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _PRIO_RE.finditer(text or ""):
        val = match.group(0).upper()
        if val not in seen:
            seen.add(val)
            found.append(val)
    return found


def parse_pm_intent(message: str) -> PmIntent | None:
    """Return a PM intent when the operator is clearly talking to the board.

    Conservative on purpose: architecture / review / escalate phrases must
    fall through to the normal Cursor path.
    """
    text = (message or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text).strip()

    create = _CREATE_RE.match(compact)
    if create:
        title = (create.group("title") or "").strip().rstrip(".")
        if not title:
            return None
        pri = (create.group("priority") or "P2").upper()
        return PmIntent(
            action="create",
            board_id="hawkeye",
            title=title[:200],
            status="Ready",
            priority=pri if re.fullmatch(r"P[0-3]", pri) else "P2",
            raw=text,
        )

    update = _UPDATE_RE.match(compact)
    if update:
        status = notion_pm.normalize_status(update.group("status") or "")
        if not status:
            return None
        return PmIntent(
            action="update",
            board_id="hawkeye",
            task_id=notion_pm.normalize_task_id(update.group("task_id") or ""),
            status=status,
            raw=text,
        )

    open_prio = _LIST_OPEN_PRIO_RE.match(compact)
    if open_prio:
        return PmIntent(
            action="list",
            board_id=_board_from_alias(None),
            priorities=_priorities_in(compact),
            open_only=True,
            raw=text,
        )

    on_board = _LIST_ON_BOARD_RE.match(compact)
    if on_board:
        return PmIntent(
            action="list",
            board_id=_board_from_alias(on_board.group("board")),
            open_only=not bool(_ALL_RE.search(compact)),
            priorities=_priorities_in(compact),
            raw=text,
        )

    list_tasks = _LIST_TASKS_RE.match(compact)
    if list_tasks:
        return PmIntent(
            action="list",
            board_id=_board_from_alias(list_tasks.group("board")),
            open_only=not bool(_ALL_RE.search(compact)),
            priorities=_priorities_in(compact),
            raw=text,
        )

    return None


def format_task_line(task: notion_pm.TaskCard) -> str:
    tid = task.task_id or task.page_id[:8] or "?"
    bits = [f"- {tid}"]
    meta = " ".join(x for x in (task.priority, task.status) if x)
    if meta:
        bits.append(f"[{meta}]")
    bits.append(task.name or "(untitled)")
    return " ".join(bits)


def format_board_reply(
    board_id: str,
    tasks: list[notion_pm.TaskCard],
    *,
    open_only: bool,
    priorities: list[str] | None = None,
    mock: bool = False,
) -> str:
    board = notion_pm.get_board(board_id)
    filt = ""
    if priorities:
        filt = f" ({'/'.join(priorities)})"
    scope = "open" if open_only else "listed"
    lines = [f"{board.name} board — {len(tasks)} {scope}{filt}:"]
    if not tasks:
        lines.append("(none)")
    else:
        for task in tasks[:15]:
            lines.append(format_task_line(task))
        if len(tasks) > 15:
            lines.append(f"… +{len(tasks) - 15} more")
    if mock:
        lines.append("(mock board — connect Notion for live cards)")
    return "\n".join(lines)


def _cards_from_mock(board_id: str) -> list[notion_pm.TaskCard]:
    data = notion_pm.mock_board_summary(board_id)
    return [notion_pm.TaskCard.from_dict(row) for row in data.get("tasks") or []]


def _query_tasks(board_id: str) -> tuple[list[notion_pm.TaskCard], bool]:
    if _env_truthy("HAWKEYE_PM_MOCK"):
        return _cards_from_mock(board_id), True
    return notion_pm.query_board_tasks(board_id, status=None, limit=100), False


def _remember_decision(intent: PmIntent, summary: str) -> str | None:
    if not _env_truthy("HAWKEYE_MEMORY_ENABLED", "1"):
        return None
    text = (summary or "").strip()
    if not text:
        return None
    try:
        from memory import get_store

        rec = get_store().remember_decision(
            text,
            meta={
                "source": "pm_chat",
                "action": intent.action,
                "board": intent.board_id,
                "task_id": intent.task_id,
            },
        )
        return rec.id
    except Exception as exc:  # noqa: BLE001
        print(f"[pm-chat] remember_decision failed: {exc}")
        return None


def execute_pm_intent(intent: PmIntent, *, remember: bool = True) -> dict[str, Any]:
    """Run a parsed PM intent against notion.pm (or mock board)."""
    out: dict[str, Any] = {
        "ok": False,
        "action": intent.action,
        "board_id": intent.board_id,
        "reply": "",
        "tasks": [],
        "task": None,
        "seeded_task": None,
        "mock": False,
        "decision_id": None,
        "intent": intent.to_dict(),
    }
    try:
        if intent.action == "list":
            cards, mock = _query_tasks(intent.board_id)
            filtered = notion_pm.filter_tasks(
                cards,
                open_only=intent.open_only,
                priorities=intent.priorities or None,
            )
            out["ok"] = True
            out["mock"] = mock
            out["tasks"] = [t.to_dict() for t in filtered]
            out["reply"] = format_board_reply(
                intent.board_id,
                filtered,
                open_only=intent.open_only,
                priorities=intent.priorities,
                mock=mock,
            )
            if remember and filtered:
                counts: dict[str, int] = {}
                for task in filtered:
                    counts[task.status or "Unknown"] = counts.get(task.status or "Unknown", 0) + 1
                count_bits = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                prio = "/".join(intent.priorities) if intent.priorities else "open"
                out["decision_id"] = _remember_decision(
                    intent,
                    f"Hawkeye board {intent.board_id}: {len(filtered)} {prio} tasks ({count_bits}).",
                )
        elif intent.action == "update":
            if _env_truthy("HAWKEYE_PM_MOCK"):
                found = None
                for card in _cards_from_mock(intent.board_id):
                    if notion_pm.normalize_task_id(card.task_id) == intent.task_id:
                        found = card
                        break
                if found is None:
                    out["reply"] = f"No mock task {intent.task_id} on the {intent.board_id} board."
                    return out
                found.status = intent.status or found.status
                out["ok"] = True
                out["mock"] = True
                out["task"] = found.to_dict()
                out["reply"] = (
                    f"Set {found.task_id} to {found.status}: {found.name} (mock — Notion not written)."
                )
            else:
                found = notion_pm.find_task_by_id(intent.task_id, intent.board_id)
                if found is None:
                    out["reply"] = (
                        f"Could not find {intent.task_id} on the {intent.board_id} board."
                    )
                    return out
                updated = notion_pm.update_task_status(found.page_id, intent.status or "Ready")
                out["ok"] = True
                out["task"] = updated.to_dict()
                out["reply"] = f"Set {updated.task_id or intent.task_id} to {updated.status}: {updated.name}"
            if remember and out["ok"]:
                out["decision_id"] = _remember_decision(intent, out["reply"])
        elif intent.action == "create":
            if _env_truthy("HAWKEYE_PM_MOCK"):
                fake = notion_pm.TaskCard(
                    page_id="mock-created",
                    task_id="HK-NEW",
                    name=intent.title,
                    status=intent.status or "Ready",
                    priority=intent.priority,
                    board_id=intent.board_id,
                )
                out["ok"] = True
                out["mock"] = True
                out["task"] = fake.to_dict()
                out["seeded_task"] = fake.page_id
                out["reply"] = (
                    f"Added {fake.status} task {fake.task_id}: {fake.name} (mock — Notion not written)."
                )
            else:
                created = notion_pm.create_task(
                    intent.title,
                    board_id=intent.board_id,
                    status=intent.status or "Ready",
                    priority=intent.priority,
                    acceptance=f"Queued from Hawkeye chat: {intent.title}",
                    notes="Created from Hawkeye chat",
                )
                out["ok"] = True
                out["task"] = created.to_dict()
                out["seeded_task"] = created.page_id
                label = created.task_id or created.page_id
                out["reply"] = f"Added {created.status} task {label}: {created.name}"
            if remember and out["ok"]:
                out["decision_id"] = _remember_decision(intent, out["reply"])
        else:
            out["reply"] = f"Unknown PM action: {intent.action}"
    except notion_pm.NotionError as exc:
        out["reply"] = f"Notion PM failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        out["reply"] = f"Notion PM failed: {exc}"
    return out
