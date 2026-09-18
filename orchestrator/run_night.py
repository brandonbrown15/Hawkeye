#!/usr/bin/env python3
"""Autocode overnight orchestrator — local-first coding with cloud escalation.

Works independently:
  Ready Notion tasks → route → local Hermes (with retries) OR cloud agent delegate.
Use --mock to simulate a full night without Notion/Hermes/hardware.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notion import client as notion  # noqa: E402
from orchestrator.checks import run_repo_checks  # noqa: E402
from orchestrator.health import check_local_stack  # noqa: E402
from orchestrator import ops  # noqa: E402
from orchestrator.policy import decide_route, target_for_tier  # noqa: E402


@dataclass
class Task:
    page_id: str
    task_id: str
    name: str
    acceptance: str
    complexity: str
    model_route: str
    repo: str
    priority: str
    notes: str = ""

    @classmethod
    def from_page(cls, page: dict[str, Any]) -> "Task":
        props = page.get("properties", {})
        tid = props.get("Task ID", {}).get("unique_id", {})
        number = tid.get("number") if isinstance(tid, dict) else None
        task_id = f"BLD-{number}" if number is not None else page["id"][:8]
        repo = (
            notion.page_prop_select(page, "Repo")
            or notion.page_prop_text(page, "Repo")
            or ""
        )
        return cls(
            page_id=page["id"],
            task_id=task_id,
            name=notion.page_title(page),
            acceptance=notion.page_prop_text(page, "Acceptance"),
            complexity=notion.page_prop_select(page, "Complexity") or "Local-safe",
            model_route=notion.page_prop_select(page, "Model route") or "Local Hermes",
            repo=repo,
            priority=notion.page_prop_select(page, "Priority") or "P2",
            notes=notion.page_prop_text(page, "Notes"),
        )


@dataclass
class HardwareSnapshot:
    mem_available_mb: int
    mem_total_mb: int
    disk_free_gb: float
    load1: float
    is_jetson: bool
    notes: list[str] = field(default_factory=list)

    def too_constrained_for_local(self) -> bool:
        min_ram = env_int("AUTOCODE_MIN_RAM_MB", 2500)
        min_disk = float(os.environ.get("AUTOCODE_MIN_DISK_GB", "5"))
        if self.mem_available_mb < min_ram:
            return True
        if self.disk_free_gb < min_disk:
            return True
        cpus = os.cpu_count() or 4
        return self.load1 > max(8.0, cpus * 2)


@dataclass
class RunResult:
    outcome: str
    summary: str
    model_used: str = "Local"
    pr_url: str | None = None
    branch: str | None = None
    escalated_to: str | None = None
    why: str | None = None


class NotionSink:
    """Real Notion API adapter (or mock)."""

    def claim(self, page_id: str) -> None:
        notion.claim_task(page_id)

    def needs_review(self, page_id: str, pr_url: str) -> None:
        notion.mark_needs_review(page_id, pr_url)

    def blocked(self, page_id: str) -> None:
        notion.mark_blocked(page_id)

    def log_run(self, name: str, outcome: str, summary: str, model: str = "Local", pr: str | None = None) -> None:
        notion.log_agent_run(name, outcome, summary, model, pr)

    def escalate(self, name: str, why: str, context: str, send_to: str = "Human", pr: str | None = None) -> None:
        notion.write_escalation(name, why, context, send_to=send_to, related_pr=pr)


class MockNotionSink(NotionSink):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []

    def _write(self, kind: str, **kwargs: Any) -> None:
        row = {"kind": kind, "ts": datetime.now(timezone.utc).isoformat(), **kwargs}
        self.events.append(row)
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[mock-notion] {kind}: {kwargs}")

    def claim(self, page_id: str) -> None:
        self._write("claim", page_id=page_id)

    def needs_review(self, page_id: str, pr_url: str) -> None:
        self._write("needs_review", page_id=page_id, pr_url=pr_url)

    def blocked(self, page_id: str) -> None:
        self._write("blocked", page_id=page_id)

    def log_run(self, name: str, outcome: str, summary: str, model: str = "Local", pr: str | None = None) -> None:
        self._write("agent_run", name=name, outcome=outcome, summary=summary, model=model, pr=pr)

    def escalate(self, name: str, why: str, context: str, send_to: str = "Human", pr: str | None = None) -> None:
        self._write("escalation", name=name, why=why, context=context, send_to=send_to, pr=pr)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s or "task")[:max_len]


def probe_hardware() -> HardwareSnapshot:
    notes: list[str] = []
    mem_total = mem_avail = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1]) // 1024
    except OSError:
        notes.append("no /proc/meminfo")

    disk_free = 0.0
    try:
        disk_free = shutil.disk_usage(str(ROOT)).free / (1024 ** 3)
    except OSError:
        notes.append("disk_usage failed")

    load1 = 0.0
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        notes.append("no loadavg")

    is_jetson = Path("/etc/nv_tegra_release").exists()
    if is_jetson:
        notes.append("jetson detected")
    return HardwareSnapshot(mem_avail, mem_total, disk_free, load1, is_jetson, notes)


def query_ready_tasks(limit: int) -> list[Task]:
    body = {
        "filter": {"property": "Status", "select": {"equals": "Ready"}},
        "sorts": [{"property": "Priority", "direction": "ascending"}],
        "page_size": limit,
    }
    result = notion.notion_request(
        "POST", f"/databases/{notion.db_id('build_queue')}/query", body
    )
    return [Task.from_page(p) for p in result.get("results", [])]


def _maybe_local_ram_issue(task: Task, hw: HardwareSnapshot) -> bool:
    return (
        task.complexity == "Maybe local"
        and hw.mem_available_mb < env_int("AUTOCODE_MAYBE_LOCAL_MIN_RAM_MB", 4000)
    )


def preferred_cloud_target(
    task: Task,
    *,
    hw: HardwareSnapshot | None = None,
    local_failures: int | None = None,
    local_stack_ok: bool = True,
) -> str:
    """Pick the cheapest cloud target this task deserves (not always Cursor)."""
    max_attempts = env_int("AUTOCODE_MAX_LOCAL_ATTEMPTS", 2)
    failures = max_attempts if local_failures is None else local_failures
    constrained = True
    if hw is not None:
        constrained = hw.too_constrained_for_local() or _maybe_local_ram_issue(task, hw)
    decision = decide_route(
        task,
        local_failures=max(failures, max_attempts),
        hardware_constrained=constrained,
        local_stack_ok=local_stack_ok,
        max_local_attempts=max_attempts,
    )
    if decision.target == "local":
        return target_for_tier("cheap")
    return decision.target


def route_task(task: Task, hw: HardwareSnapshot, local_failures: int) -> str:
    """Cost-aware route: local when cheap/safe; else cheapest sufficient cloud model."""
    decision = decide_route(
        task,
        local_failures=local_failures,
        hardware_constrained=hw.too_constrained_for_local() or _maybe_local_ram_issue(task, hw),
        local_stack_ok=True,
        max_local_attempts=env_int("AUTOCODE_MAX_LOCAL_ATTEMPTS", 2),
    )
    return decision.target


def attempts_path(task_id: str) -> Path:
    p = ROOT / "state" / "attempts"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{task_id}.json"


def load_attempts(task_id: str) -> int:
    path = attempts_path(task_id)
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text()).get("failures", 0))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


def save_attempts(task_id: str, failures: int) -> None:
    attempts_path(task_id).write_text(json.dumps({"failures": failures, "updated": datetime.now(timezone.utc).isoformat()}))


def clear_attempts(task_id: str) -> None:
    path = attempts_path(task_id)
    if path.exists():
        path.unlink()


def workspace_for_repo(repo: str) -> Path:
    root = Path(os.environ.get("WORKSPACE_ROOT", str(Path.home() / "workspaces")))
    if not repo:
        return root / "default"
    name = repo.rstrip("/").split("/")[-1].removesuffix(".git")
    return root / name


def ensure_branch(repo_dir: Path, branch: str) -> None:
    if not (repo_dir / ".git").exists():
        raise RuntimeError(f"Not a git repo: {repo_dir}")
    subprocess.run(["git", "fetch", "--all"], cwd=repo_dir, check=False, capture_output=True)
    for base in ("main", "master"):
        r = subprocess.run(["git", "checkout", base], cwd=repo_dir, capture_output=True)
        if r.returncode == 0:
            break
    subprocess.run(["git", "checkout", "-B", branch], cwd=repo_dir, check=True)


def build_prompt(task: Task, branch: str) -> str:
    return f"""You are Autocode local Hermes — an always-on coding autopilot.

Task: {task.task_id} — {task.name}
Priority: {task.priority}
Complexity: {task.complexity}
Branch: {branch}

Acceptance criteria:
{task.acceptance or "(none — make a minimal safe change and document assumptions)"}

Notes:
{task.notes or "(none)"}

Rules:
- Stay inside acceptance criteria.
- Never merge main. Never invent secrets.
- Prefer a small PR-ready change.
- Run available tests/linters.
- If stuck after honest attempts, stop and say ESCALATE: <reason>.
- If you notice a clear follow-up improvement or bug outside this task, end with:
  IMPROVE: <short actionable checklist item>
  or BUG: <short actionable bug to fix>
  Autocode will add those to the Notion Ready checklist automatically.
"""


def maybe_open_pr(repo_dir: Path, branch: str, task: Task) -> str | None:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True
    )
    if status.stdout.strip():
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=False)
        subprocess.run(
            ["git", "commit", "-m", f"{task.task_id}: {task.name}"],
            cwd=repo_dir,
            check=False,
        )
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_dir, check=False)
    if not shutil.which("gh"):
        return None
    pr = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", f"{task.task_id}: {task.name}",
            "--body", f"Autocode overnight run.\n\n## Acceptance\n{task.acceptance}\n",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if pr.returncode != 0:
        return None
    url = pr.stdout.strip().splitlines()[-1].strip()
    return url if url.startswith("http") else None


def run_local_hermes(
    task: Task,
    repo_dir: Path,
    branch: str,
    wall_minutes: int,
    mock: bool = False,
) -> RunResult:
    prompt = build_prompt(task, branch)
    state = ROOT / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / f"prompt-{task.task_id}.txt").write_text(prompt)

    if mock:
        marker = repo_dir / "AUTOCODE_MOCK_CHANGE.md"
        marker.write_text(f"# Mock change for {task.task_id}\n\n{task.acceptance}\n")
        ok, check_log = run_repo_checks(repo_dir)
        pr_url = maybe_open_pr(repo_dir, branch, task) or f"https://example.invalid/pr/{task.task_id}"
        if not ok:
            return RunResult(
                outcome="Failed",
                summary=f"Mock local change but checks failed:\n{check_log}",
                branch=branch,
                why="Tests failing",
            )
        return RunResult(
            outcome="Success",
            summary=f"Mock local Hermes success; PR {pr_url}",
            pr_url=pr_url,
            branch=branch,
        )

    hermes = shutil.which("hermes")
    if not hermes:
        return RunResult(
            outcome="Failed",
            summary="hermes CLI not found — install Hermes or escalate",
            branch=branch,
            why="Tool fail",
        )

    try:
        proc = subprocess.run(
            [hermes, "chat", "-q", prompt],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=wall_minutes * 60,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            outcome="Failed",
            summary=f"Local Hermes hit wall time ({wall_minutes}m)",
            branch=branch,
            why="Too complex",
        )

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (state / f"hermes-{task.task_id}.log").write_text(out)

    if proc.returncode != 0:
        return RunResult(
            outcome="Failed",
            summary=f"Hermes exit {proc.returncode}: {out[-500:]}",
            branch=branch,
            why="Tool fail",
        )
    if re.search(r"ESCALATE:", out, re.I):
        return RunResult(
            outcome="Failed",
            summary=out[-800:],
            branch=branch,
            why="Too complex",
        )

    ok, check_log = run_repo_checks(repo_dir)
    (state / f"checks-{task.task_id}.log").write_text(check_log)
    if not ok:
        return RunResult(
            outcome="Failed",
            summary=f"Repo checks failed:\n{check_log[-1500:]}",
            branch=branch,
            why="Tests failing",
        )

    pr_url = maybe_open_pr(repo_dir, branch, task)
    if pr_url:
        return RunResult(
            outcome="Success",
            summary=f"Local Hermes finished; PR {pr_url}",
            pr_url=pr_url,
            branch=branch,
        )

    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True
    )
    if dirty.stdout.strip():
        return RunResult(
            outcome="Partial",
            summary="Local changes on branch but no PR opened",
            branch=branch,
        )
    return RunResult(
        outcome="Partial",
        summary="Hermes OK but no file changes detected",
        branch=branch,
    )


def write_delegate_payload(task: Task, target: str, why: str, context: str) -> Path:
    out_dir = ROOT / "state" / "delegates"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{task.task_id}-{int(time.time())}.json"
    payload = {
        "task": asdict(task),
        "send_to": target,
        "why": why,
        "context": context,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "branch_hint": f"{os.environ.get('AUTOCODE_BRANCH_PREFIX', 'hermes')}/{task.task_id.lower()}-{slugify(task.name)}",
        "instructions": (
            "Cloud agent: implement acceptance criteria on a feature branch, "
            "open a PR, never merge main, never invent secrets. "
            "Prefer the smallest change that satisfies acceptance."
        ),
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def cloud_coding_prompt(task: Task, context: str) -> str:
    return (
        f"Autocode delegated this task because local Jetson capacity was insufficient "
        f"or the task is marked for cloud.\n\n"
        f"Task: {task.task_id} — {task.name}\n"
        f"Repo: {task.repo}\n"
        f"Acceptance:\n{task.acceptance}\n\n"
        f"Context:\n{context[:3000]}\n\n"
        f"Implement on a feature branch, open a PR, do not merge main, do not invent secrets."
    )


def anthropic_delegate(task: Task, context: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    body = {
        "model": os.environ.get("AUTOCODE_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "max_tokens": int(os.environ.get("AUTOCODE_CLAUDE_MAX_TOKENS", "1024")),
        "messages": [{"role": "user", "content": cloud_coding_prompt(task, context)}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    parts = data.get("content", [])
    text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return text[:2000] or "Claude acknowledged escalation"


def openrouter_delegate(task: Task, context: str) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("AUTOCODE_OPENROUTER_MODEL", "x-ai/grok-2")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a coding agent receiving an Autocode escalation."},
            {"role": "user", "content": cloud_coding_prompt(task, context)},
        ],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"][:2000]


def xai_grok_delegate(task: Task, context: str) -> str:
    """Direct xAI Grok API (https://api.x.ai/v1)."""
    api_key = os.environ["XAI_API_KEY"]
    model = os.environ.get("AUTOCODE_GROK_MODEL", "grok-2-latest")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are Grok Bot receiving an Autocode escalation."},
            {"role": "user", "content": cloud_coding_prompt(task, context)},
        ],
    }
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"][:2000]


def model_label_for_target(target: str) -> str:
    return {
        "Claude": "Claude",
        "Grok Bot": "Grok",
        "Cursor Cloud": "Cursor",
        "Human": "Local",
    }.get(target, "Mixed")


def invoke_cloud_delegate(
    task: Task,
    target: str,
    why: str,
    context: str,
    mock: bool = False,
) -> RunResult:
    payload_path = write_delegate_payload(task, target, why, context)

    if mock:
        return RunResult(
            outcome="Escalated",
            summary=f"[mock] Escalated to {target}; payload {payload_path}",
            model_used=model_label_for_target(target),
            escalated_to=target,
            why=why,
        )

    custom = os.environ.get("AUTOCODE_CURSOR_DELEGATE_CMD", "").strip()
    if target == "Cursor Cloud" and custom:
        try:
            subprocess.run(
                custom,
                shell=True,
                check=True,
                cwd=str(ROOT),
                env={**os.environ, "AUTOCODE_DELEGATE_PAYLOAD": str(payload_path)},
                timeout=env_int("AUTOCODE_DELEGATE_TIMEOUT_SEC", 120),
            )
            return RunResult(
                outcome="Escalated",
                summary=f"Delegated to Cursor via AUTOCODE_CURSOR_DELEGATE_CMD; {payload_path}",
                model_used="Cursor",
                escalated_to=target,
                why=why,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            context = f"{context}\nDelegate cmd failed: {e}"

    if target == "Claude" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            reply = anthropic_delegate(task, context)
            (ROOT / "state" / f"claude-{task.task_id}.txt").write_text(reply)
            return RunResult(
                outcome="Escalated",
                summary=f"Delegated to Claude; payload {payload_path}; reply_len={len(reply)}",
                model_used="Claude",
                escalated_to=target,
                why=why,
            )
        except Exception as e:  # noqa: BLE001
            context = f"{context}\nClaude delegate failed: {e}"

    # Custom Grok Bot webhook / Telegram / xAI agent launcher
    grok_cmd = os.environ.get("AUTOCODE_GROK_DELEGATE_CMD", "").strip()
    if target == "Grok Bot" and grok_cmd:
        try:
            subprocess.run(
                grok_cmd,
                shell=True,
                check=True,
                cwd=str(ROOT),
                env={**os.environ, "AUTOCODE_DELEGATE_PAYLOAD": str(payload_path)},
                timeout=env_int("AUTOCODE_DELEGATE_TIMEOUT_SEC", 120),
            )
            return RunResult(
                outcome="Escalated",
                summary=f"Delegated to Grok Bot via AUTOCODE_GROK_DELEGATE_CMD; {payload_path}",
                model_used="Grok",
                escalated_to=target,
                why=why,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            context = f"{context}\nGrok delegate cmd failed: {e}"

    if target == "Grok Bot" and os.environ.get("XAI_API_KEY"):
        try:
            reply = xai_grok_delegate(task, context)
            (ROOT / "state" / f"grok-{task.task_id}.txt").write_text(reply)
            return RunResult(
                outcome="Escalated",
                summary=f"Delegated to xAI Grok; payload {payload_path}; reply_len={len(reply)}",
                model_used="Grok",
                escalated_to=target,
                why=why,
            )
        except Exception as e:  # noqa: BLE001
            context = f"{context}\nxAI Grok delegate failed: {e}"

    if target == "Grok Bot" and os.environ.get("OPENROUTER_API_KEY"):
        try:
            reply = openrouter_delegate(task, context)
            (ROOT / "state" / f"grok-{task.task_id}.txt").write_text(reply)
            return RunResult(
                outcome="Escalated",
                summary=f"Delegated to Grok via OpenRouter; payload {payload_path}; reply_len={len(reply)}",
                model_used="Grok",
                escalated_to=target,
                why=why,
            )
        except Exception as e:  # noqa: BLE001
            context = f"{context}\nOpenRouter delegate failed: {e}"

    return RunResult(
        outcome="Escalated",
        summary=f"Escalated to {target}. Payload: {payload_path}. Awaiting cloud/human agent.",
        model_used=model_label_for_target(target),
        escalated_to=target,
        why=why,
    )


def process_task(
    task: Task,
    hw: HardwareSnapshot,
    digest: list[str],
    sink: NotionSink,
    mock: bool = False,
) -> RunResult:
    prefix = os.environ.get("AUTOCODE_BRANCH_PREFIX", "hermes")
    branch = f"{prefix}/{task.task_id.lower()}-{slugify(task.name)}"
    wall = env_int("AUTOCODE_MAX_WALL_MINUTES", 90)
    max_attempts = env_int("AUTOCODE_MAX_LOCAL_ATTEMPTS", 2)

    prior_failures = 0 if mock else load_attempts(task.task_id)
    decision = decide_route(
        task,
        local_failures=prior_failures,
        hardware_constrained=hw.too_constrained_for_local() or _maybe_local_ram_issue(task, hw),
        local_stack_ok=True,
        max_local_attempts=max_attempts,
    )
    route = decision.target
    sink.claim(task.page_id)

    # Local stack health gate — escalate to scored tier, not always premium
    if route == "local" and not mock:
        health = check_local_stack()
        print("Local health:", "; ".join(health.details))
        if not health.local_ready:
            decision = decide_route(
                task,
                local_failures=prior_failures,
                hardware_constrained=hw.too_constrained_for_local()
                or _maybe_local_ram_issue(task, hw),
                local_stack_ok=False,
                max_local_attempts=max_attempts,
            )
            route = decision.target if decision.target != "local" else target_for_tier("cheap")
            prior_failures = max_attempts  # force escalate path messaging

    if route != "local":
        why = "Tool fail" if hw.too_constrained_for_local() else "Too complex"
        context = (
            f"Routed to {route} [score={decision.score} tier={decision.tier}] "
            f"({decision.reason}; complexity={task.complexity}, "
            f"model_route={task.model_route}, prior_failures={prior_failures}, hw={asdict(hw)})"
        )
        ops.write_status(
            phase="escalating",
            task_id=task.task_id,
            task_name=task.name,
            route=route,
            detail=why,
        )
        result = invoke_cloud_delegate(task, route, why, context, mock=mock)
        sink.escalate(task.name, why, result.summary, send_to=result.escalated_to or route)
        sink.log_run(task.name, result.outcome, result.summary, result.model_used, result.pr_url)
        if result.escalated_to == "Human":
            sink.blocked(task.page_id)
        digest.append(
            f"ESCALATED {task.task_id} → {route} "
            f"[score={decision.score}/{decision.tier}]: {task.name}"
        )
        return result

    repo_dir = workspace_for_repo(task.repo)
    if mock and not repo_dir.exists():
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "autocode@mock"], cwd=repo_dir, check=False)
        subprocess.run(["git", "config", "user.name", "Autocode Mock"], cwd=repo_dir, check=False)
        (repo_dir / "README.md").write_text("# mock repo\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=False)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=False)

    if not repo_dir.exists():
        target = preferred_cloud_target(task, hw=hw, local_failures=max_attempts)
        result = invoke_cloud_delegate(
            task,
            target,
            "Tool fail",
            f"Workspace missing: {repo_dir}. Clone WORKSPACE_REPOS first.",
            mock=mock,
        )
        sink.escalate(task.name, "Tool fail", result.summary, send_to=target)
        sink.log_run(task.name, result.outcome, result.summary, result.model_used)
        if target == "Human":
            sink.blocked(task.page_id)
        digest.append(f"ESCALATED {task.task_id} (missing repo) → {target}: {task.name}")
        return result

    try:
        ensure_branch(repo_dir, branch)
    except Exception as e:  # noqa: BLE001
        result = RunResult(
            outcome="Failed",
            summary=f"git branch failed: {e}",
            why="Tool fail",
            branch=branch,
        )
        sink.escalate(task.name, "Tool fail", result.summary, send_to="Human")
        sink.log_run(task.name, result.outcome, result.summary)
        sink.blocked(task.page_id)
        digest.append(f"FAILED {task.task_id} git: {task.name}")
        return result

    # Local attempts with retry
    failures = prior_failures
    last: RunResult | None = None
    while failures < max_attempts:
        ops.write_status(
            phase="running_local",
            task_id=task.task_id,
            task_name=task.name,
            route="local",
            detail=f"local attempt {failures + 1}/{max_attempts}",
        )
        ops.heartbeat(detail=f"local attempt {failures + 1}/{max_attempts}")
        last = run_local_hermes(task, repo_dir, branch, wall, mock=mock)
        if last.outcome in ("Success", "Partial"):
            clear_attempts(task.task_id)
            if last.pr_url and last.outcome == "Success":
                sink.needs_review(task.page_id, last.pr_url)
            sink.log_run(task.name, last.outcome, last.summary, last.model_used, last.pr_url)
            digest.append(
                f"{last.outcome.upper()} {task.task_id}: {task.name} {last.pr_url or ''}".strip()
            )
            try:
                from orchestrator.self_feed import feed_from_agent_output

                feed_from_agent_output(
                    last.summary, repo=getattr(task, "repo", "") or "", mock=mock
                )
            except Exception as _sf:  # noqa: BLE001
                print(f"[self-feed] post-success hook failed: {_sf}")
            return last
        failures += 1
        save_attempts(task.task_id, failures)
        print(f"Local attempt {failures}/{max_attempts} failed: {last.summary[:200]}")
        if (last.why or "") == "Tests failing" or "checks failed" in (last.summary or "").lower():
            try:
                from orchestrator.self_feed import feed_from_check_failure

                feed_from_check_failure(
                    last.summary,
                    repo=getattr(task, "repo", "") or "",
                    task_name=task.name,
                    mock=mock,
                )
            except Exception as _sf:  # noqa: BLE001
                print(f"[self-feed] check-failure hook failed: {_sf}")
        if failures < max_attempts:
            time.sleep(2)

    assert last is not None
    fail_decision = decide_route(
        task,
        local_failures=failures,
        hardware_constrained=hw.too_constrained_for_local() or _maybe_local_ram_issue(task, hw),
        local_stack_ok=True,
        max_local_attempts=max_attempts,
    )
    target = (
        fail_decision.target
        if fail_decision.target != "local"
        else preferred_cloud_target(task, hw=hw, local_failures=failures)
    )
    why = last.why or "Too complex"
    esc = invoke_cloud_delegate(
        task,
        target,
        why,
        f"{last.summary} | cost policy: {fail_decision.reason}",
        mock=mock,
    )
    sink.escalate(task.name, why, esc.summary, send_to=target)
    sink.log_run(task.name, "Escalated", esc.summary, esc.model_used)
    if target == "Human":
        sink.blocked(task.page_id)
    clear_attempts(task.task_id)
    digest.append(
        f"ESCALATED {task.task_id} after {failures} local fails → {target} "
        f"[score={fail_decision.score}/{fail_decision.tier}]"
    )
    return esc


def mock_tasks() -> list[Task]:
    return [
        Task(
            page_id="mock-local-1",
            task_id="BLD-101",
            name="Docs typo fix",
            acceptance="Add a short note file documenting Autocode mock run.",
            complexity="Local-safe",
            model_route="Local Hermes",
            repo="mock-app",
            priority="P1",
        ),
        Task(
            page_id="mock-mid-1",
            task_id="BLD-103",
            name="API handler cleanup",
            acceptance="Refactor one HTTP handler; no auth or infra changes.",
            complexity="Cloud-only",
            model_route="Local Hermes",
            repo="mock-app",
            priority="P2",
        ),
        Task(
            page_id="mock-cloud-1",
            task_id="BLD-102",
            name="Auth redesign",
            acceptance="Redesign auth architecture across services.",
            complexity="Cloud-only",
            model_route="Cursor Cloud",
            repo="mock-app",
            priority="P0",
        ),
    ]


def send_digest(path: Path) -> None:
    script = ROOT / "scripts" / "send_telegram_digest.sh"
    if script.exists():
        subprocess.run([str(script), str(path)], check=False)



def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def main() -> None:
    notion.load_dotenv()
    parser = argparse.ArgumentParser(
        description="Autocode project autopilot — drain Notion Ready work until done"
    )
    parser.add_argument("--dry-run", action="store_true", help="Route only; no claim/execute")
    parser.add_argument("--mock", action="store_true", help="Simulate a full cycle without Notion/Hermes")
    parser.add_argument("--limit", type=int, default=None, help="Tasks per batch")
    parser.add_argument(
        "--drain",
        action="store_true",
        help="Keep pulling Ready tasks until the queue is empty (or safety cap)",
    )
    parser.add_argument("--force-low-ram", action="store_true", help="Simulate constrained hardware")
    parser.add_argument(
        "--skip-health-feed",
        action="store_true",
        help="Do not seed routine health/bug checklist items this cycle",
    )
    args = parser.parse_args()

    drain = args.drain or _env_truthy("AUTOCODE_DRAIN_UNTIL_EMPTY", "0")
    batch = args.limit or env_int(
        "AUTOCODE_MAX_TASKS_PER_CYCLE" if drain else "AUTOCODE_MAX_TASKS_PER_NIGHT",
        1 if drain else 2,
    )
    hard_cap = env_int("AUTOCODE_MAX_TASKS_PER_DRAIN", 50)
    hw = probe_hardware()
    if args.force_low_ram:
        hw = HardwareSnapshot(
            512,
            hw.mem_total_mb,
            hw.disk_free_gb,
            hw.load1,
            hw.is_jetson,
            hw.notes + ["forced low RAM"],
        )
    print(f"Hardware: {asdict(hw)}")
    print(f"Mode: {'drain-until-empty' if drain else 'single-batch'} batch={batch} cap={hard_cap}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    digest_path = ROOT / "state" / f"digest-{stamp}.txt"
    digest_path.parent.mkdir(parents=True, exist_ok=True)

    run_id = stamp
    ops.set_control(clear=True)
    ops.write_status(
        phase="starting",
        night_id=run_id,
        detail="autopilot cycle starting",
        clear_task=True,
    )
    ops.telegram_notify(f"Autocode cycle {run_id} starting (mock={args.mock}, drain={drain})")

    if args.mock:
        os.environ.setdefault(
            "AUTOCODE_CURSOR_DELEGATE_CMD",
            str(ROOT / "scripts" / "delegate_cursor_stub.sh"),
        )
        sink: NotionSink = MockNotionSink(ROOT / "state" / "mock_notion.jsonl")
        # Keep mock git work outside this Autocode checkout
        mock_ws = Path("/tmp/autocode-mock-workspaces")
        mock_ws.mkdir(parents=True, exist_ok=True)
        os.environ["WORKSPACE_ROOT"] = str(mock_ws)
    else:
        if not notion.resolve_notion_token():
            raise SystemExit(
                "Notion token required — Account → Connections → Notion "
                "or NOTION_TOKEN in .env (or pass --mock)"
            )
        sink = NotionSink()

    if not args.skip_health_feed and not args.dry_run:
        try:
            from orchestrator.self_feed import maybe_seed_routine_health

            maybe_seed_routine_health(mock=args.mock, force=False)
        except Exception as e:  # noqa: BLE001
            print(f"[self-feed] routine health seed skipped: {e}")

    digest: list[str] = [
        f"Autocode digest {datetime.now(timezone.utc).isoformat()} drain={drain}"
    ]
    processed = 0
    aborted = False

    while True:
        if args.mock:
            tasks = mock_tasks() if processed == 0 else []
        else:
            tasks = query_ready_tasks(limit=batch)

        if not tasks:
            if processed == 0:
                print("No Ready tasks.")
                digest.append("No Ready tasks.")
                ops.write_status(phase="done", detail="no ready tasks", clear_task=True)
                ops.telegram_notify(f"Autocode cycle {run_id}: no Ready tasks")
            else:
                print("Ready queue drained.")
                digest.append(f"Drained Ready queue after {processed} task(s).")
            break

        for task in tasks[:batch]:
            if processed >= hard_cap:
                digest.append(f"Hit safety cap AUTOCODE_MAX_TASKS_PER_DRAIN={hard_cap}")
                ops.telegram_notify(
                    f"Autocode cycle {run_id}: hit drain safety cap ({hard_cap})"
                )
                break

            flags = ops.wait_if_paused()
            if flags.abort:
                digest.append(f"ABORTED before {task.task_id}")
                ops.write_status(phase="aborted", detail=f"abort before {task.task_id}")
                ops.telegram_notify(f"Autocode ABORTED before {task.task_id}")
                aborted = True
                break
            if ops.should_skip(task.task_id):
                ops.clear_skip(task.task_id)
                digest.append(f"SKIPPED {task.task_id}: {task.name}")
                ops.telegram_notify(f"Autocode SKIPPED {task.task_id}")
                continue

            prior = 0 if args.mock else load_attempts(task.task_id)
            decision = decide_route(
                task,
                local_failures=prior,
                hardware_constrained=hw.too_constrained_for_local()
                or _maybe_local_ram_issue(task, hw),
                max_local_attempts=env_int("AUTOCODE_MAX_LOCAL_ATTEMPTS", 2),
            )
            route = decision.target
            ops.write_status(
                phase="routing",
                task_id=task.task_id,
                task_name=task.name,
                route=route,
                detail=decision.reason,
                night_id=run_id,
            )
            print(
                f"Task {task.task_id} {task.name!r} → route={route} "
                f"[score={decision.score} tier={decision.tier}] "
                f"({decision.reason}; prior_failures={prior})"
            )
            if args.dry_run and not args.mock:
                digest.append(
                    f"DRY-RUN {task.task_id} → {route} "
                    f"[score={decision.score}/{decision.tier}]"
                )
                processed += 1
                continue
            ops.telegram_notify(
                f"Autocode {task.task_id} → {route} [{decision.tier}] {task.name}"
            )
            process_task(task, hw, digest, sink, mock=args.mock)
            processed += 1

        if aborted or processed >= hard_cap or not drain or args.mock:
            break

    final = ops.load_control()
    phase = "aborted" if (aborted or final.abort) else "done"
    ops.write_status(
        phase=phase,
        detail=f"cycle finished processed={processed}",
        clear_task=True,
    )
    digest_path.write_text("\n".join(digest) + "\n")
    print(f"Digest: {digest_path}")
    print("\n".join(digest))
    ops.telegram_notify(f"Autocode cycle {run_id} {phase}\n" + "\n".join(digest[-8:]))
    send_digest(digest_path)


if __name__ == "__main__":
    main()
