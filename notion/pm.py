"""Hawkeye project-management views over Notion databases.

Raises NotionError (not SystemExit) so the UI can return JSON errors.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from notion import client as nc

NOTION_VERSION = nc.NOTION_VERSION
API = nc.API

ALLOWED_STATUSES = {
    "Backlog",
    "Ready",
    "Running",
    "Needs review",
    "Done",
    "Blocked",
    "Now",
    "Next",
    "Parked",
    "Open",
    "Answered",
    "Deferred",
}

CLOSED_STATUSES = frozenset({"done", "parked", "answered", "deferred"})

_STATUS_ALIASES = {
    "done": "Done",
    "complete": "Done",
    "completed": "Done",
    "finished": "Done",
    "ready": "Ready",
    "blocked": "Blocked",
    "backlog": "Backlog",
    "running": "Running",
    "in progress": "Running",
    "needs review": "Needs review",
    "review": "Needs review",
    "now": "Now",
    "next": "Next",
    "parked": "Parked",
    "open": "Open",
    "answered": "Answered",
    "deferred": "Deferred",
}

_TASK_ID_RE = re.compile(r"^([A-Za-z]{1,8})-?(\d{1,6})$")


class NotionError(Exception):
    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Board:
    id: str
    name: str
    kind: str  # build_queue | projects
    env_key: str
    description: str = ""
    configured: bool = False
    db_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskCard:
    page_id: str
    task_id: str
    name: str
    status: str
    priority: str = ""
    complexity: str = ""
    model_route: str = ""
    area: str = ""
    acceptance: str = ""
    notes: str = ""
    branch_pr: str = ""
    repo: str = ""
    url: str = ""
    board_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskCard":
        extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
        return cls(
            page_id=str(data.get("page_id") or ""),
            task_id=str(data.get("task_id") or ""),
            name=str(data.get("name") or ""),
            status=str(data.get("status") or ""),
            priority=str(data.get("priority") or ""),
            complexity=str(data.get("complexity") or ""),
            model_route=str(data.get("model_route") or ""),
            area=str(data.get("area") or ""),
            acceptance=str(data.get("acceptance") or ""),
            notes=str(data.get("notes") or ""),
            branch_pr=str(data.get("branch_pr") or ""),
            repo=str(data.get("repo") or ""),
            url=str(data.get("url") or ""),
            board_id=str(data.get("board_id") or ""),
            extra=dict(extra),
        )


# Known BrownHawke boards (env overrides win).
_BOARD_DEFAULTS: list[dict[str, str]] = [
    {
        "id": "hawkeye",
        "name": "Hawkeye",
        "kind": "build_queue",
        "env_key": "NOTION_BUILD_QUEUE_DB",
        "default_db": "71e3f07a3dda41ae85f158c1f24e82b8",
        "description": "Hawkeye product Build Queue — team engineering work",
    },
    {
        "id": "rose",
        "name": "ROSE Projects",
        "kind": "projects",
        "env_key": "NOTION_ROSE_PROJECTS_DB",
        "default_db": "2059e55eb7e246f3940fab422a51b2aa",
        "description": "ROSE Planning Hub projects",
    },
    {
        "id": "autocode",
        "name": "Autocode / Coding Machine",
        "kind": "build_queue",
        "env_key": "NOTION_LCM_BUILD_QUEUE_DB",
        "default_db": "6b1e564b106e437eac995a9b66da379a",
        "description": "Local Coding Machine Build Queue",
    },
]


def _token() -> str:
    try:
        from ui import connections

        return connections.resolve_secret("notion", "token")
    except Exception:  # noqa: BLE001
        return os.environ.get("NOTION_TOKEN", "").strip()


def notion_api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _token()
    if not token:
        raise NotionError(
            "Notion token not set. Add it under Account → Connections → Notion "
            "(or set NOTION_TOKEN in .env / connect_notion.sh for machine autopilot).",
            status=503,
        )
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise NotionError(f"Notion HTTP {e.code}: {detail}", status=502) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NotionError(f"Notion unreachable: {e}", status=502) from e


def resolve_db_id(env_key: str, default_db: str = "") -> str | None:
    value = os.environ.get(env_key, "").strip().replace("-", "")
    if value:
        return value
    # Prefer explicit Hawkeye queue when NOTION_BUILD_QUEUE_DB unset but defaults allowed.
    if default_db and os.environ.get("HAWKEYE_NOTION_USE_DEFAULTS", "1").lower() in (
        "1",
        "true",
        "yes",
    ):
        return default_db.replace("-", "")
    return None


def list_boards() -> list[Board]:
    boards: list[Board] = []
    for row in _BOARD_DEFAULTS:
        db = resolve_db_id(row["env_key"], row.get("default_db", ""))
        boards.append(
            Board(
                id=row["id"],
                name=row["name"],
                kind=row["kind"],
                env_key=row["env_key"],
                description=row["description"],
                configured=bool(db) and bool(_token()),
                db_id=db,
            )
        )
    return boards


def get_board(board_id: str) -> Board:
    for b in list_boards():
        if b.id == board_id:
            return b
    raise NotionError(f"Unknown board: {board_id}", status=404)


def _unique_id(page: dict[str, Any], prop: str = "Task ID") -> str:
    props = page.get("properties", {}) or {}
    # Prefer Task ID, then generic ID
    for key in (prop, "ID", "Id"):
        raw = props.get(key) or {}
        uid = raw.get("unique_id") or {}
        num = uid.get("number")
        prefix = uid.get("prefix") or ""
        if num is not None:
            if prefix:
                return f"{prefix}-{num}"
            return f"BLD-{num}" if key == "Task ID" else str(num)
    return ""


def _page_url(page: dict[str, Any]) -> str:
    url = page.get("url") or ""
    if url:
        return str(url)
    pid = str(page.get("id", "")).replace("-", "")
    return f"https://www.notion.so/{pid}" if pid else ""


def _page_prop_url(page: dict[str, Any], name: str) -> str:
    prop = page.get("properties", {}).get(name) or {}
    return str(prop.get("url") or "")


def serialize_build_queue_page(page: dict[str, Any], *, board_id: str) -> TaskCard:
    area = nc.page_prop_select(page, "Area") or ""
    repo = nc.page_prop_select(page, "Repo") or nc.page_prop_text(page, "Repo")
    return TaskCard(
        page_id=str(page.get("id") or ""),
        task_id=_unique_id(page, "Task ID"),
        name=nc.page_title(page),
        status=nc.page_prop_select(page, "Status") or "",
        priority=nc.page_prop_select(page, "Priority") or "",
        complexity=nc.page_prop_select(page, "Complexity") or "",
        model_route=nc.page_prop_select(page, "Model route") or "",
        area=area,
        acceptance=nc.page_prop_text(page, "Acceptance"),
        notes=nc.page_prop_text(page, "Notes"),
        branch_pr=_page_prop_url(page, "Branch / PR"),
        repo=repo or "",
        url=_page_url(page),
        board_id=board_id,
    )


def serialize_rose_project(page: dict[str, Any], *, board_id: str) -> TaskCard:
    props = page.get("properties", {}) or {}
    areas = props.get("Area", {}).get("multi_select") or []
    area = ", ".join(a.get("name", "") for a in areas if isinstance(a, dict))
    return TaskCard(
        page_id=str(page.get("id") or ""),
        task_id=_unique_id(page, "ID") or _unique_id(page, "Task ID"),
        name=nc.page_title(page),
        status=nc.page_prop_select(page, "Status") or "",
        priority=nc.page_prop_select(page, "Priority") or "",
        complexity="",
        model_route=nc.page_prop_select(page, "Owner AI") or "",
        area=area,
        acceptance=nc.page_prop_text(page, "Next step") or nc.page_prop_text(page, "Summary"),
        notes=nc.page_prop_text(page, "Summary"),
        branch_pr=_page_prop_url(page, "PR/Link") or _page_prop_url(page, "PR / Link"),
        repo="",
        url=_page_url(page),
        board_id=board_id,
        extra={
            "owner_ai": nc.page_prop_select(page, "Owner AI") or "",
            "next_step": nc.page_prop_text(page, "Next step"),
        },
    )


def query_board_tasks(
    board_id: str = "hawkeye",
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[TaskCard]:
    board = get_board(board_id)
    if not board.db_id:
        raise NotionError(
            f"Board {board_id} has no database id. Set {board.env_key} in .env.",
            status=503,
        )
    limit = max(1, min(int(limit), 100))
    body: dict[str, Any] = {"page_size": limit}
    if status and status.lower() not in ("all", "*", ""):
        body["filter"] = {"property": "Status", "select": {"equals": status}}
    # Priority sort works on build queues; ROSE may also have Priority.
    body["sorts"] = [{"property": "Priority", "direction": "ascending"}]
    try:
        result = notion_api("POST", f"/databases/{board.db_id}/query", body)
    except NotionError:
        # Retry without sort if property missing on some DBs.
        body.pop("sorts", None)
        result = notion_api("POST", f"/databases/{board.db_id}/query", body)

    pages = result.get("results") or []
    out: list[TaskCard] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        if board.kind == "projects":
            out.append(serialize_rose_project(page, board_id=board.id))
        else:
            out.append(serialize_build_queue_page(page, board_id=board.id))
    return out


def get_task(page_id: str, *, board_id: str = "hawkeye") -> TaskCard:
    page_id = page_id.strip()
    if not page_id:
        raise NotionError("page_id required", status=400)
    page = notion_api("GET", f"/pages/{page_id}")
    board = get_board(board_id)
    if board.kind == "projects":
        return serialize_rose_project(page, board_id=board.id)
    return serialize_build_queue_page(page, board_id=board.id)


def normalize_task_id(raw: str) -> str:
    text = (raw or "").strip()
    match = _TASK_ID_RE.match(text)
    if not match:
        return text.upper()
    return f"{match.group(1).upper()}-{match.group(2)}"


def normalize_status(raw: str) -> str | None:
    text = re.sub(r"\s+", " ", (raw or "").strip().rstrip("."))
    text = re.sub(r"(?i)\s+please$", "", text).strip()
    if not text:
        return None
    for allowed in ALLOWED_STATUSES:
        if text.lower() == allowed.lower():
            return allowed
    return _STATUS_ALIASES.get(text.lower())


def is_open_status(status: str) -> bool:
    return (status or "").strip().lower() not in CLOSED_STATUSES


def filter_tasks(
    tasks: list[TaskCard],
    *,
    open_only: bool = False,
    priorities: list[str] | None = None,
    status: str | None = None,
) -> list[TaskCard]:
    prios = {p.strip().upper() for p in (priorities or []) if str(p).strip()}
    status_l = (status or "").strip().lower()
    out: list[TaskCard] = []
    for task in tasks:
        if open_only and not is_open_status(task.status):
            continue
        if status_l and status_l not in ("all", "*", "") and (task.status or "").lower() != status_l:
            continue
        if prios and (task.priority or "").upper() not in prios:
            continue
        out.append(task)
    return out


def find_task_by_id(task_id: str, board_id: str = "hawkeye") -> TaskCard | None:
    wanted = normalize_task_id(task_id)
    if not wanted:
        return None
    for task in query_board_tasks(board_id, status=None, limit=100):
        if normalize_task_id(task.task_id) == wanted:
            return task
    return None


def create_task(
    name: str,
    *,
    board_id: str = "hawkeye",
    status: str = "Ready",
    priority: str = "P2",
    acceptance: str = "",
    notes: str = "",
    complexity: str = "Local-safe",
    model_route: str = "Local Hermes",
    area: str = "",
) -> TaskCard:
    """Insert a Build Queue card (Hawkeye / Autocode boards)."""
    board = get_board(board_id)
    if not board.db_id:
        raise NotionError(
            f"Board {board_id} has no database id. Set {board.env_key} in .env.",
            status=503,
        )
    if board.kind == "projects":
        raise NotionError(
            "Creating tasks on ROSE Projects is not supported from chat yet. Use the Hawkeye board.",
            status=400,
        )
    name = (name or "").strip()
    if not name:
        raise NotionError("task name required", status=400)
    resolved = normalize_status(status) or (status or "").strip()
    if resolved not in ALLOWED_STATUSES:
        raise NotionError(f"Unsupported status: {status}", status=400)
    priority = (priority or "P2").strip().upper()
    if not re.fullmatch(r"P[0-3]", priority):
        raise NotionError(f"Unsupported priority: {priority}", status=400)
    props: dict[str, Any] = {
        "Name": {"title": nc.title(name)},
        "Status": {"select": {"name": resolved}},
        "Priority": {"select": {"name": priority}},
        "Complexity": {"select": {"name": complexity or "Local-safe"}},
        "Model route": {"select": {"name": model_route or "Local Hermes"}},
        "Acceptance": {
            "rich_text": nc.rich_text(acceptance or f"Queued from Hawkeye chat: {name}")
        },
        "Notes": {"rich_text": nc.rich_text(notes or "Created from Hawkeye chat")},
    }
    if area:
        props["Area"] = {"select": {"name": area}}
    page = notion_api(
        "POST",
        "/pages",
        {"parent": {"database_id": board.db_id}, "properties": props},
    )
    return serialize_build_queue_page(page, board_id=board.id)


def update_task_status(page_id: str, status: str, *, pr_url: str | None = None) -> TaskCard:
    status = normalize_status(status) or (status or "").strip()
    if status not in ALLOWED_STATUSES:
        raise NotionError(f"Unsupported status: {status}", status=400)
    props: dict[str, Any] = {"Status": {"select": {"name": status}}}
    if pr_url:
        props["Branch / PR"] = {"url": pr_url}
    page = notion_api("PATCH", f"/pages/{page_id}", {"properties": props})
    # Infer board from response parent if possible; default hawkeye serializer.
    return serialize_build_queue_page(page, board_id="hawkeye")


def board_summary(board_id: str = "hawkeye") -> dict[str, Any]:
    tasks = query_board_tasks(board_id, status=None, limit=100)
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.status or "Unknown"] = counts.get(t.status or "Unknown", 0) + 1
    return {
        "board": get_board(board_id).to_dict(),
        "total": len(tasks),
        "counts": counts,
        "tasks": [t.to_dict() for t in tasks],
    }


def mock_board_summary(board_id: str = "hawkeye") -> dict[str, Any]:
    """Offline fixture so the UI can be demoed without NOTION_TOKEN."""
    board = get_board(board_id)
    sample = [
        TaskCard(
            page_id="mock-1",
            task_id="HK-2",
            name="Deploy Hawkeye UI behind hawkeye.brownhawke.engineering",
            status="Ready",
            priority="P0",
            complexity="Maybe local",
            area="Deploy",
            acceptance="Tunnel serves login UI over HTTPS",
            board_id=board_id,
            url="https://app.notion.com/",
        ),
        TaskCard(
            page_id="mock-2",
            task_id="HK-5",
            name="Unified orchestrator: manage other AIs end-to-end",
            status="Ready",
            priority="P1",
            complexity="Cloud-only",
            area="Integrations",
            acceptance="User talks only to Hawkeye",
            board_id=board_id,
            url="https://app.notion.com/",
        ),
        TaskCard(
            page_id="mock-3",
            task_id="HK-1",
            name="Grant Cursor access and push Hawkeye private main",
            status="Needs review",
            priority="P0",
            complexity="Local-safe",
            area="Deploy",
            acceptance="Private repo clone works on Jetson",
            board_id=board_id,
            branch_pr="https://github.com/brandonbrown15/Hawkeye/pull/1",
            url="https://app.notion.com/",
        ),
        TaskCard(
            page_id="mock-4",
            task_id="HK-6",
            name="Expand Hawkeye into general engineering PM",
            status="Ready",
            priority="P2",
            complexity="Cloud-only",
            area="Product",
            acceptance="Team can manage projects in Hawkeye",
            board_id=board_id,
            url="https://app.notion.com/",
        ),
    ]
    counts: dict[str, int] = {}
    for t in sample:
        counts[t.status] = counts.get(t.status, 0) + 1
    return {
        "board": board.to_dict(),
        "total": len(sample),
        "counts": counts,
        "tasks": [t.to_dict() for t in sample],
        "mock": True,
    }
