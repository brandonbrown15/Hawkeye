"""Hawkeye project-management views over Notion databases.

Raises NotionError (not SystemExit) so the UI can return JSON errors.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from notion import client as nc

NOTION_VERSION = nc.NOTION_VERSION
API = nc.API


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


def update_task_status(page_id: str, status: str, *, pr_url: str | None = None) -> TaskCard:
    status = (status or "").strip()
    allowed = {
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
    if status not in allowed:
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
