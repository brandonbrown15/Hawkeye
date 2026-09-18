#!/usr/bin/env python3
"""Minimal Notion helpers for Autocode overnight loop.

Uses the Notion REST API with NOTION_TOKEN from the environment.
No secrets are stored in-repo. Share Build Queue / Agent Runs / Escalation Log
with the integration before running.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def resolve_notion_token() -> str:
    """Prefer Account → Connections Notion token, then machine NOTION_TOKEN.

    Overnight / worker (no HTTP session) looks up the autopilot operator vault:
    HAWKEYE_AUTOPILOT_EMAIL, else first HAWKEYE_ADMIN_EMAILS entry, else Brandon.
    """
    try:
        from ui import connections

        tok = connections.resolve_secret("notion", "token")
        if tok:
            return tok
        auto = os.environ.get("HAWKEYE_AUTOPILOT_EMAIL", "").strip()
        if not auto:
            admins = os.environ.get("HAWKEYE_ADMIN_EMAILS")
            if admins is None:
                auto = "brandon@brownhawke.engineering"
            else:
                auto = next((x.strip() for x in admins.split(",") if x.strip()), "")
        if auto:
            tok = connections.resolve_secret("notion", "token", email=auto)
            if tok:
                return tok
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("NOTION_TOKEN", "").strip()


def notion_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = resolve_notion_token()
    if not token:
        raise SystemExit(
            "Notion token required — add under Account → Connections → Notion "
            "or set NOTION_TOKEN in .env on the Jetson"
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"Notion HTTP {e.code}: {detail}") from e


def db_id(name: str) -> str:
    key = {
        "build_queue": "NOTION_BUILD_QUEUE_DB",
        "agent_runs": "NOTION_AGENT_RUNS_DB",
        "escalation_log": "NOTION_ESCALATION_LOG_DB",
    }[name]
    value = os.environ.get(key, "").strip()
    if not value:
        raise SystemExit(f"{key} missing from environment")
    return value


def rich_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text[:1900]}}]


def title(text: str) -> list[dict[str, Any]]:
    return rich_text(text)


def query_ready_local_safe(limit: int = 5) -> list[dict[str, Any]]:
    """Fetch Ready + Local-safe tasks ordered for overnight pickup."""
    body = {
        "filter": {
            "and": [
                {"property": "Status", "select": {"equals": "Ready"}},
                {"property": "Complexity", "select": {"equals": "Local-safe"}},
            ]
        },
        "sorts": [{"property": "Priority", "direction": "ascending"}],
        "page_size": limit,
    }
    result = notion_request("POST", f"/databases/{db_id('build_queue')}/query", body)
    return result.get("results", [])


def page_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {})
    t = props.get("Name", {}).get("title", [])
    if not t:
        return "(untitled)"
    return "".join(part.get("plain_text", "") for part in t)


def page_prop_select(page: dict[str, Any], name: str) -> str | None:
    sel = page.get("properties", {}).get(name, {}).get("select")
    return sel.get("name") if sel else None


def page_prop_text(page: dict[str, Any], name: str) -> str:
    rich = page.get("properties", {}).get(name, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rich)


def set_task_status(page_id: str, status: str, pr_url: str | None = None) -> None:
    props: dict[str, Any] = {"Status": {"select": {"name": status}}}
    if pr_url:
        props["Branch / PR"] = {"url": pr_url}
    notion_request("PATCH", f"/pages/{page_id}", {"properties": props})


def claim_task(page_id: str) -> None:
    set_task_status(page_id, "Running")


def mark_needs_review(page_id: str, pr_url: str) -> None:
    set_task_status(page_id, "Needs review", pr_url=pr_url)


def mark_blocked(page_id: str) -> None:
    set_task_status(page_id, "Blocked")


def log_agent_run(
    name: str,
    outcome: str,
    summary: str,
    model_used: str = "Local",
    pr_url: str | None = None,
) -> None:
    props: dict[str, Any] = {
        "Name": {"title": title(name)},
        "Outcome": {"select": {"name": outcome}},
        "Summary": {"rich_text": rich_text(summary)},
        "Model used": {"select": {"name": model_used}},
    }
    if pr_url:
        props["PR / commit"] = {"url": pr_url}
    notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": db_id("agent_runs")}, "properties": props},
    )


def write_escalation(
    name: str,
    why: str,
    context: str,
    send_to: str = "Human",
    related_pr: str | None = None,
) -> None:
    props: dict[str, Any] = {
        "Name": {"title": title(name)},
        "Status": {"select": {"name": "Open"}},
        "Why escalated": {"select": {"name": why}},
        "Send to": {"select": {"name": send_to}},
        "Context": {"rich_text": rich_text(context)},
    }
    if related_pr:
        props["Related PR"] = {"url": related_pr}
    notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": db_id("escalation_log")}, "properties": props},
    )


def cmd_list_ready(_: argparse.Namespace) -> None:
    pages = query_ready_local_safe(limit=int(os.environ.get("AUTOCODE_MAX_TASKS_PER_NIGHT", "2")))
    if not pages:
        print("No Ready + Local-safe tasks.")
        return
    for page in pages:
        tid = page.get("properties", {}).get("Task ID", {})
        task_id = tid.get("unique_id", {}).get("number") or "?"
        print(
            f"BLD-{task_id}\t{page_title(page)}\t"
            f"prio={page_prop_select(page, 'Priority')}\t"
            f"repo={page_prop_select(page, 'Repo')}\t"
            f"accept={page_prop_text(page, 'Acceptance')[:80]}"
        )
        print(f"  id={page['id']}")


def cmd_doctor(_: argparse.Namespace) -> None:
    """Verify token + DB access. Exit 0 only if all configured DBs respond."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("FAIL: NOTION_TOKEN unset")
        raise SystemExit(1)

    checks = [
        ("build_queue", "NOTION_BUILD_QUEUE_DB"),
        ("agent_runs", "NOTION_AGENT_RUNS_DB"),
        ("escalation_log", "NOTION_ESCALATION_LOG_DB"),
    ]
    failed = 0
    for name, env_key in checks:
        value = os.environ.get(env_key, "").strip()
        if not value:
            print(f"WARN: {env_key} unset — skip")
            continue
        try:
            notion_request("GET", f"/databases/{value}")
            print(f"OK   {name} ({env_key})")
        except SystemExit as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    if failed:
        raise SystemExit(1)
    if not any(os.environ.get(k, "").strip() for _, k in checks):
        print("FAIL: no Notion database IDs configured")
        raise SystemExit(1)
    print("Notion doctor passed")


def cmd_claim(args: argparse.Namespace) -> None:
    claim_task(args.page_id)
    print(f"Claimed {args.page_id} → Running")


def upsert_env(key: str, value: str) -> None:
    """Write or replace KEY=value in ROOT/.env (creates file if needed)."""
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
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
    env_path.write_text("\n".join(out) + "\n")
    os.environ[key] = value


def _select_options(*names: str) -> dict[str, Any]:
    return {"select": {"options": [{"name": n} for n in names]}}


def _find_child_database(parent_page_id: str, title_text: str) -> str | None:
    """Return database id if a child DB with this title already exists."""
    cursor = None
    while True:
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "database"},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", "/search", body)
        for item in result.get("results", []):
            if item.get("object") != "database":
                continue
            parent = item.get("parent") or {}
            if parent.get("type") == "page_id" and parent.get("page_id") == parent_page_id:
                titles = item.get("title") or []
                name = "".join(t.get("plain_text", "") for t in titles)
                if name == title_text:
                    return item["id"]
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return None


def _create_database(parent_page_id: str, title_text: str, properties: dict[str, Any]) -> str:
    existing = _find_child_database(parent_page_id, title_text)
    if existing:
        print(f"Reuse existing DB '{title_text}' → {existing}")
        return existing
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title_text}}],
        "properties": properties,
    }
    created = notion_request("POST", "/databases", body)
    db = created["id"]
    print(f"Created DB '{title_text}' → {db}")
    return db


def provision_databases(parent_page_id: str) -> dict[str, str]:
    """Create Build Queue / Agent Runs / Escalation Log under a shared hub page."""
    build_props = {
        "Name": {"title": {}},
        "Status": _select_options(
            "Backlog", "Ready", "Running", "Needs review", "Done", "Blocked"
        ),
        "Priority": _select_options("P0", "P1", "P2", "P3"),
        "Complexity": _select_options("Local-safe", "Maybe local", "Cloud-only"),
        "Model route": _select_options("Local Hermes", "Claude", "Grok", "Cursor Cloud"),
        "Repo": {"rich_text": {}},
        "Acceptance": {"rich_text": {}},
        "Branch / PR": {"url": {}},
        "Notes": {"rich_text": {}},
        "Task ID": {"unique_id": {"prefix": "BLD"}},
    }
    runs_props = {
        "Name": {"title": {}},
        "Outcome": _select_options("Success", "Partial", "Failed", "Escalated", "Skipped"),
        "Summary": {"rich_text": {}},
        "Model used": _select_options("Local", "Claude", "Grok", "Cursor", "Mixed"),
        "PR / commit": {"url": {}},
    }
    esc_props = {
        "Name": {"title": {}},
        "Status": _select_options("Open", "Assigned", "Resolved"),
        "Why escalated": _select_options(
            "Too complex", "Tool fail", "Tests failing", "Needs secrets", "Ambiguous"
        ),
        "Send to": _select_options("Claude", "Grok Bot", "Cursor Cloud", "Human"),
        "Context": {"rich_text": {}},
        "Related PR": {"url": {}},
    }

    ids = {
        "NOTION_BUILD_QUEUE_DB": _create_database(parent_page_id, "Build Queue", build_props),
        "NOTION_AGENT_RUNS_DB": _create_database(parent_page_id, "Agent Runs", runs_props),
        "NOTION_ESCALATION_LOG_DB": _create_database(
            parent_page_id, "Escalation Log", esc_props
        ),
    }
    upsert_env("NOTION_HUB_PAGE", parent_page_id)
    for key, value in ids.items():
        upsert_env(key, value)
    # Keep ids.yaml in sync when present/expected
    ids_path = ROOT / "notion" / "ids.yaml"
    ids_path.write_text(
        "\n".join(
            [
                f"build_queue: {ids['NOTION_BUILD_QUEUE_DB']}",
                f"agent_runs: {ids['NOTION_AGENT_RUNS_DB']}",
                f"escalation_log: {ids['NOTION_ESCALATION_LOG_DB']}",
                f"hub_page: {parent_page_id}",
                "",
            ]
        )
    )
    return ids


def seed_ready_task(
    name: str,
    acceptance: str,
    repo: str = "",
    priority: str = "P3",
    complexity: str = "Local-safe",
    model_route: str = "Local Hermes",
) -> str:
    """Insert one Ready task for the first supervised/auto night."""
    props: dict[str, Any] = {
        "Name": {"title": title(name)},
        "Status": {"select": {"name": "Ready"}},
        "Priority": {"select": {"name": priority}},
        "Complexity": {"select": {"name": complexity}},
        "Model route": {"select": {"name": model_route}},
        "Acceptance": {"rich_text": rich_text(acceptance)},
        "Notes": {"rich_text": rich_text("Seeded by Autocode go-live")},
    }
    if repo:
        props["Repo"] = {"rich_text": rich_text(repo)}
    page = notion_request(
        "POST",
        "/pages",
        {"parent": {"database_id": db_id("build_queue")}, "properties": props},
    )
    return page["id"]


def cmd_provision(args: argparse.Namespace) -> None:
    parent = (
        args.parent
        or os.environ.get("NOTION_HUB_PAGE", "").strip()
        or os.environ.get("NOTION_PARENT_PAGE", "").strip()
    )
    if not parent:
        raise SystemExit(
            "Need a Notion parent page id: pass --parent or set NOTION_HUB_PAGE.\n"
            "Create an empty page, share it with your Autocode integration, then re-run."
        )
    ids = provision_databases(parent)
    print("Wrote DB ids to .env and notion/ids.yaml")
    for k, v in ids.items():
        print(f"  {k}={v}")
    if args.seed:
        page_id = seed_ready_task(
            name=args.seed_title,
            acceptance=args.seed_acceptance,
            repo=args.seed_repo or "",
        )
        print(f"Seeded Ready task → {page_id}")


def cmd_seed(args: argparse.Namespace) -> None:
    page_id = seed_ready_task(
        name=args.title,
        acceptance=args.acceptance,
        repo=args.repo or "",
        priority=args.priority,
        complexity=args.complexity,
        model_route=args.model_route,
    )
    print(f"Seeded Ready task → {page_id}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Autocode Notion helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-ready", help="List Ready + Local-safe Build Queue items")
    p_list.set_defaults(func=cmd_list_ready)

    p_doc = sub.add_parser("doctor", help="Verify Notion token + database access")
    p_doc.set_defaults(func=cmd_doctor)

    p_prov = sub.add_parser(
        "provision",
        help="Auto-create Build Queue / Agent Runs / Escalation Log under NOTION_HUB_PAGE",
    )
    p_prov.add_argument("--parent", help="Notion parent page id (defaults to NOTION_HUB_PAGE)")
    p_prov.add_argument("--seed", action="store_true", help="Also insert one Ready Local-safe task")
    p_prov.add_argument("--seed-title", default="Autocode smoke: add README tip")
    p_prov.add_argument(
        "--seed-acceptance",
        default="Open a tiny PR that adds one helpful sentence to README. Do not touch secrets.",
    )
    p_prov.add_argument("--seed-repo", default="")
    p_prov.set_defaults(func=cmd_provision)

    p_seed = sub.add_parser("seed", help="Insert a Ready Local-safe Build Queue task")
    p_seed.add_argument("--title", default="Autocode smoke: add README tip")
    p_seed.add_argument(
        "--acceptance",
        default="Open a tiny PR that adds one helpful sentence to README. Do not touch secrets.",
    )
    p_seed.add_argument("--repo", default="")
    p_seed.add_argument("--priority", default="P3")
    p_seed.add_argument("--complexity", default="Local-safe")
    p_seed.add_argument("--model-route", default="Local Hermes")
    p_seed.set_defaults(func=cmd_seed)

    p_claim = sub.add_parser("claim", help="Mark a Build Queue page Running")
    p_claim.add_argument("page_id")
    p_claim.set_defaults(func=cmd_claim)

    p_review = sub.add_parser("needs-review", help="Mark Needs review + set PR URL")
    p_review.add_argument("page_id")
    p_review.add_argument("pr_url")
    p_review.set_defaults(
        func=lambda a: (mark_needs_review(a.page_id, a.pr_url), print("updated"))
    )

    p_run = sub.add_parser("log-run", help="Create an Agent Runs row")
    p_run.add_argument("name")
    p_run.add_argument("outcome", choices=["Success", "Partial", "Failed", "Escalated", "Skipped"])
    p_run.add_argument("summary")
    p_run.add_argument("--pr")
    p_run.add_argument("--model", default="Local")
    p_run.set_defaults(
        func=lambda a: (
            log_agent_run(a.name, a.outcome, a.summary, a.model, a.pr),
            print("logged"),
        )
    )

    p_esc = sub.add_parser("escalate", help="Write Escalation Log row")
    p_esc.add_argument("name")
    p_esc.add_argument(
        "why",
        choices=["Too complex", "Tool fail", "Tests failing", "Needs secrets", "Ambiguous"],
    )
    p_esc.add_argument("context")
    p_esc.add_argument("--send-to", default="Human")
    p_esc.add_argument("--pr")
    p_esc.set_defaults(
        func=lambda a: (
            write_escalation(a.name, a.why, a.context, a.send_to, a.pr),
            print("escalated"),
        )
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
