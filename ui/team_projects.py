"""Account-scoped Hawkeye projects with coworker sharing.

Separate from Notion boards (`/api/projects`). These are Hawkeye-owned
workspaces that can be private to one user or shared with teammates.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ui import accounts
from ui import auth as ui_auth

_LOCK = threading.RLock()


def projects_path() -> Path:
    return accounts.accounts_root() / "projects.json"


def _load() -> dict[str, Any]:
    path = projects_path()
    if not path.is_file():
        return {"projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"projects": {}}
    if not isinstance(data, dict):
        return {"projects": {}}
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    return {"projects": projects}


def _save(data: dict[str, Any]) -> None:
    path = projects_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _member_role(project: dict[str, Any], email: str) -> str | None:
    email = ui_auth.normalize_email(email)
    if ui_auth.normalize_email(str(project.get("owner_email") or "")) == email:
        return "owner"
    for m in project.get("members") or []:
        if isinstance(m, dict) and ui_auth.normalize_email(str(m.get("email") or "")) == email:
            return str(m.get("role") or "viewer")
    return None


def _can_read(project: dict[str, Any], email: str) -> bool:
    return _member_role(project, email) is not None


def _can_edit(project: dict[str, Any], email: str) -> bool:
    return _member_role(project, email) in ("owner", "editor")


def _public(project: dict[str, Any], email: str) -> dict[str, Any]:
    members = []
    for m in project.get("members") or []:
        if not isinstance(m, dict):
            continue
        mem_email = ui_auth.normalize_email(str(m.get("email") or ""))
        if not mem_email:
            continue
        profile = accounts.get_profile(mem_email)
        members.append(
            {
                "email": mem_email,
                "role": m.get("role") or "viewer",
                "display_name": profile.get("display_name"),
            }
        )
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "description": project.get("description") or "",
        "owner_email": project.get("owner_email"),
        "members": members,
        "notion_board_id": project.get("notion_board_id") or "",
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
        "my_role": _member_role(project, email),
    }


def list_projects(email: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load()
        rows = []
        for proj in (data.get("projects") or {}).values():
            if isinstance(proj, dict) and _can_read(proj, email):
                rows.append(_public(proj, email))
    rows.sort(key=lambda p: float(p.get("updated_at") or 0), reverse=True)
    return {"ok": True, "projects": rows}


def create_project(
    email: str,
    *,
    name: str,
    description: str = "",
    notion_board_id: str = "",
) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    pid = "proj_" + uuid.uuid4().hex[:10]
    now = time.time()
    project = {
        "id": pid,
        "name": name,
        "description": (description or "").strip(),
        "owner_email": email,
        "members": [{"email": email, "role": "owner"}],
        "notion_board_id": (notion_board_id or "").strip(),
        "created_at": now,
        "updated_at": now,
    }
    with _LOCK:
        data = _load()
        projects = dict(data.get("projects") or {})
        projects[pid] = project
        data["projects"] = projects
        _save(data)
    return {"ok": True, "project": _public(project, email)}


def get_project(email: str, project_id: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load()
        project = (data.get("projects") or {}).get(project_id)
        if not isinstance(project, dict) or not _can_read(project, email):
            raise ValueError("project not found")
        return {"ok": True, "project": _public(project, email)}


def update_project(
    email: str,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    notion_board_id: str | None = None,
) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load()
        projects = dict(data.get("projects") or {})
        project = projects.get(project_id)
        if not isinstance(project, dict) or not _can_edit(project, email):
            raise ValueError("project not found or not editable")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("name required")
            project["name"] = name
        if description is not None:
            project["description"] = description.strip()
        if notion_board_id is not None:
            project["notion_board_id"] = notion_board_id.strip()
        project["updated_at"] = time.time()
        projects[project_id] = project
        data["projects"] = projects
        _save(data)
        return {"ok": True, "project": _public(project, email)}


def share_project(email: str, project_id: str, *, member_email: str, role: str = "editor") -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    member_email = ui_auth.normalize_email(member_email)
    role = (role or "editor").strip().lower()
    if role not in ("owner", "editor", "viewer"):
        raise ValueError("role must be owner|editor|viewer")
    if not ui_auth.is_allowed_email(member_email):
        raise ValueError("member must be on the allowed work domain")
    if member_email not in ui_auth.load_users():
        raise ValueError("member has no Hawkeye login yet — add them with ./scripts/hawkeye accounts set-password first")
    with _LOCK:
        data = _load()
        projects = dict(data.get("projects") or {})
        project = projects.get(project_id)
        if not isinstance(project, dict):
            raise ValueError("project not found")
        if _member_role(project, email) != "owner":
            raise ValueError("only the owner can share")
        members = [
            m
            for m in (project.get("members") or [])
            if isinstance(m, dict)
            and ui_auth.normalize_email(str(m.get("email") or "")) != member_email
        ]
        members.append({"email": member_email, "role": role})
        # Keep owner present.
        owner = ui_auth.normalize_email(str(project.get("owner_email") or ""))
        if not any(ui_auth.normalize_email(str(m.get("email") or "")) == owner for m in members):
            members.append({"email": owner, "role": "owner"})
        project["members"] = members
        if role == "owner":
            project["owner_email"] = member_email
        project["updated_at"] = time.time()
        projects[project_id] = project
        data["projects"] = projects
        _save(data)
        return {"ok": True, "project": _public(project, email)}


def unshare_project(email: str, project_id: str, member_email: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    member_email = ui_auth.normalize_email(member_email)
    with _LOCK:
        data = _load()
        projects = dict(data.get("projects") or {})
        project = projects.get(project_id)
        if not isinstance(project, dict):
            raise ValueError("project not found")
        if _member_role(project, email) != "owner":
            raise ValueError("only the owner can remove members")
        owner = ui_auth.normalize_email(str(project.get("owner_email") or ""))
        if member_email == owner:
            raise ValueError("cannot remove the owner")
        project["members"] = [
            m
            for m in (project.get("members") or [])
            if isinstance(m, dict)
            and ui_auth.normalize_email(str(m.get("email") or "")) != member_email
        ]
        project["updated_at"] = time.time()
        projects[project_id] = project
        data["projects"] = projects
        _save(data)
        return {"ok": True, "project": _public(project, email)}


def delete_project(email: str, project_id: str) -> dict[str, Any]:
    email = ui_auth.normalize_email(email)
    with _LOCK:
        data = _load()
        projects = dict(data.get("projects") or {})
        project = projects.get(project_id)
        if not isinstance(project, dict):
            raise ValueError("project not found")
        if _member_role(project, email) != "owner":
            raise ValueError("only the owner can delete")
        projects.pop(project_id, None)
        data["projects"] = projects
        _save(data)
    return {"ok": True, "deleted": project_id}
