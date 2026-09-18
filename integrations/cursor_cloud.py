"""Cursor Cloud Agents API client (v1).

Hawkeye escalate previously required a custom inbound webhook. With a Cursor
API key (Dashboard → API Keys), we create agents via:

  POST https://api.cursor.com/v1/agents

Auth: Basic (api_key as username, empty password) or Bearer — both accepted.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = os.environ.get("CURSOR_API_BASE", "https://api.cursor.com").rstrip("/")
TERMINAL = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})


class CursorCloudError(RuntimeError):
    """Raised when the Cloud Agents API rejects a request or times out oddly."""


def _auth_header(api_key: str) -> str:
    token = (api_key or "").strip()
    if not token:
        raise CursorCloudError("CURSOR_API_KEY is empty")
    # Prefer Basic like the official curl examples (`-u KEY:`).
    raw = base64.b64encode(f"{token}:".encode()).decode()
    return f"Basic {raw}"


def _request(
    method: str,
    path: str,
    api_key: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "Authorization": _auth_header(api_key),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Hawkeye/1.0",
    }
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise CursorCloudError(f"Cursor API {method} {path} → HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise CursorCloudError(f"Cursor API {method} {path} network error: {e}") from e
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CursorCloudError(f"Cursor API returned non-JSON: {raw[:200]}") from e
    if not isinstance(parsed, dict):
        raise CursorCloudError(f"Cursor API unexpected JSON type: {type(parsed)}")
    return parsed


def resolve_repository(*, explicit: str | None = None, allow_git_fallback: bool = True) -> str:
    """HTTPS GitHub URL for coding agents. Empty string = no-repo (Q&A) agent."""
    for candidate in (
        (explicit or "").strip(),
        os.environ.get("CURSOR_REPOSITORY", "").strip(),
        os.environ.get("HAWKEYE_CURSOR_REPO", "").strip(),
        os.environ.get("CURSOR_REPO_URL", "").strip(),
    ):
        if candidate:
            return _normalize_repo_url(candidate)
    if not allow_git_fallback:
        return ""
    # Fall back to origin remote when running inside the Hawkeye checkout.
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        if out:
            return _normalize_repo_url(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _normalize_repo_url(url: str) -> str:
    url = url.strip()
    if url.startswith("git@"):
        # git@github.com:org/repo.git → https://github.com/org/repo
        path = url.split(":", 1)[-1]
        if path.endswith(".git"):
            path = path[:-4]
        host = url.split("@", 1)[-1].split(":", 1)[0]
        return f"https://{host}/{path}"
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("ssh://git@"):
        # ssh://git@github.com/org/repo
        rest = url[len("ssh://git@") :]
        return f"https://{rest[:-4] if rest.endswith('.git') else rest}"
    return url


def create_agent(
    api_key: str,
    prompt: str,
    *,
    repository: str | None = None,
    ref: str | None = None,
    auto_create_pr: bool = False,
    model_id: str | None = None,
    name: str | None = None,
    mode: str = "agent",
    allow_git_fallback: bool = True,
) -> dict[str, Any]:
    """Create a Cloud Agent + initial run. Returns {agent, run, url, agent_id, run_id}."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise CursorCloudError("prompt is empty")

    body: dict[str, Any] = {"prompt": {"text": prompt}}
    if name:
        body["name"] = name[:100]
    if mode in ("agent", "plan"):
        body["mode"] = mode
    mid = (model_id or os.environ.get("CURSOR_AGENT_MODEL", "")).strip()
    if mid:
        body["model"] = {"id": mid}

    repo = resolve_repository(explicit=repository, allow_git_fallback=allow_git_fallback)
    if repo:
        entry: dict[str, Any] = {"url": repo}
        branch = (ref or os.environ.get("CURSOR_REPOSITORY_REF", "") or "main").strip()
        if branch:
            entry["startingRef"] = branch
        body["repos"] = [entry]
        body["autoCreatePR"] = bool(auto_create_pr) or env_truthy("CURSOR_AUTO_CREATE_PR", "0")

    data = _request("POST", "/v1/agents", api_key, body=body, timeout=90)
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    agent_id = str(agent.get("id") or data.get("id") or "")
    run_id = str(run.get("id") or agent.get("latestRunId") or "")
    url = str(agent.get("url") or (f"https://cursor.com/agents/{agent_id}" if agent_id else ""))
    if not agent_id:
        raise CursorCloudError(f"Cursor create-agent response missing agent id: {data}")
    return {
        "raw": data,
        "agent": agent,
        "run": run,
        "agent_id": agent_id,
        "run_id": run_id,
        "url": url,
        "repository": repo,
    }


def get_run(api_key: str, agent_id: str, run_id: str) -> dict[str, Any]:
    return _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}", api_key, timeout=60)


def wait_for_run(
    api_key: str,
    agent_id: str,
    run_id: str,
    *,
    timeout_sec: float | None = None,
    poll_sec: float | None = None,
) -> dict[str, Any]:
    """Poll until the run is terminal or timeout. Returns last run payload (+ timed_out)."""
    if not run_id:
        return {"status": "UNKNOWN", "timed_out": True, "result": ""}
    timeout = float(
        timeout_sec
        if timeout_sec is not None
        else os.environ.get("CURSOR_AGENT_WAIT_SEC", os.environ.get("AUTOCODE_DELEGATE_TIMEOUT_SEC", "120"))
    )
    interval = float(poll_sec if poll_sec is not None else os.environ.get("CURSOR_AGENT_POLL_SEC", "4"))
    deadline = time.monotonic() + max(5.0, timeout)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = get_run(api_key, agent_id, run_id)
        status = str(last.get("status") or "").upper()
        if status in TERMINAL:
            last["timed_out"] = False
            return last
        time.sleep(max(1.0, interval))
    last = last or {"status": "RUNNING"}
    last["timed_out"] = True
    return last


def format_reply(
    *,
    url: str,
    run: dict[str, Any],
    agent_id: str,
) -> str:
    status = str(run.get("status") or "UNKNOWN").upper()
    result = str(run.get("result") or "").strip()
    parts: list[str] = []
    if result:
        parts.append(result)
    if status == "FINISHED":
        parts.append(f"Cursor Cloud Agent finished: {url}")
    elif run.get("timed_out"):
        parts.append(
            f"Cursor Cloud Agent still running ({status or 'RUNNING'}). "
            f"Follow progress: {url}"
        )
    elif status in ("ERROR", "CANCELLED", "EXPIRED"):
        parts.append(f"Cursor Cloud Agent ended with {status}: {url}")
    else:
        parts.append(f"Cursor Cloud Agent: {url} (status={status})")
    git = run.get("git") if isinstance(run.get("git"), dict) else {}
    branches = git.get("branches") if isinstance(git.get("branches"), list) else []
    for b in branches[:3]:
        if not isinstance(b, dict):
            continue
        branch = b.get("branch") or ""
        pr = b.get("prUrl") or ""
        if pr:
            parts.append(f"PR: {pr}")
        elif branch:
            parts.append(f"Branch: {branch}")
    if agent_id and not any(agent_id in p for p in parts):
        parts.append(f"agent_id={agent_id}")
    return "\n".join(p for p in parts if p).strip()


def run_prompt(
    api_key: str,
    prompt: str,
    *,
    repository: str | None = None,
    ref: str | None = None,
    auto_create_pr: bool = False,
    wait: bool = True,
    timeout_sec: float | None = None,
    name: str | None = None,
    mode: str = "agent",
    allow_git_fallback: bool = True,
) -> dict[str, Any]:
    """Create an agent and optionally wait for the first run to finish."""
    created = create_agent(
        api_key,
        prompt,
        repository=repository,
        ref=ref,
        auto_create_pr=auto_create_pr,
        name=name,
        mode=mode,
        allow_git_fallback=allow_git_fallback,
    )
    run: dict[str, Any] = dict(created.get("run") or {})
    if wait and created.get("run_id"):
        run = wait_for_run(
            api_key,
            created["agent_id"],
            created["run_id"],
            timeout_sec=timeout_sec,
        )
    reply = format_reply(url=created["url"], run=run, agent_id=created["agent_id"])
    return {
        **created,
        "run": run,
        "reply": reply,
        "status": str(run.get("status") or created.get("run", {}).get("status") or ""),
    }


def escalate_chat(
    api_key: str,
    prompt: str,
    *,
    repository: str | None = None,
    wait: bool = True,
) -> str:
    """UI chat escalate: prefer no-repo Q&A unless a repository is configured."""
    # Do not invent a repo from `git remote` for chat — only env / Connections.
    repo = resolve_repository(explicit=repository, allow_git_fallback=False)
    # Chat handoffs usually want a plan/answer quickly; coding uses overnight.
    mode = "plan" if not repo else "agent"
    out = run_prompt(
        api_key,
        prompt,
        repository=repo or None,
        auto_create_pr=bool(repo) and env_truthy("CURSOR_AUTO_CREATE_PR", "0"),
        wait=wait,
        name="Hawkeye chat escalate",
        mode=mode,
        allow_git_fallback=False,
    )
    return out["reply"]


def delegate_from_payload(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Overnight / shell delegate: payload from orchestrator write_delegate_payload()."""
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    name = str(task.get("name") or payload.get("why") or "Hawkeye overnight")
    acceptance = str(task.get("acceptance") or "")
    context = str(payload.get("context") or "")
    instructions = str(payload.get("instructions") or "")
    prompt = (
        f"Hawkeye / Autocode delegated this task.\n\n"
        f"Task: {task.get('task_id', '')} — {name}\n"
        f"Repo hint: {task.get('repo', '')}\n"
        f"Why: {payload.get('why', '')}\n\n"
        f"Acceptance:\n{acceptance}\n\n"
        f"Context:\n{context[:4000]}\n\n"
        f"{instructions}"
    ).strip()
    repo_hint = str(task.get("repo") or "").strip()
    repository = None
    if repo_hint.startswith("http") or repo_hint.startswith("git@"):
        repository = repo_hint
    elif "/" in repo_hint and not repo_hint.startswith("."):
        # org/name style
        repository = f"https://github.com/{repo_hint}"
    wait = env_truthy("CURSOR_AGENT_WAIT_OVERNIGHT", "0")
    return run_prompt(
        api_key,
        prompt,
        repository=repository,
        auto_create_pr=True,
        wait=wait,
        name=f"Hawkeye: {name}"[:100],
        mode="agent",
    )


def env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        print("FAIL: CURSOR_API_KEY unset", file=sys.stderr)
        return 1

    payload_path = os.environ.get("AUTOCODE_DELEGATE_PAYLOAD", "").strip()
    if "--payload" in argv:
        i = argv.index("--payload")
        payload_path = argv[i + 1] if i + 1 < len(argv) else payload_path
    if payload_path:
        data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
        out = delegate_from_payload(api_key, data)
        print(json.dumps({"ok": True, "url": out.get("url"), "status": out.get("status"), "reply": out.get("reply")}, indent=2))
        return 0

    if "--prompt" in argv:
        i = argv.index("--prompt")
        prompt = argv[i + 1] if i + 1 < len(argv) else ""
    else:
        prompt = " ".join(argv).strip()
    if not prompt:
        print("Usage: python -m integrations.cursor_cloud --prompt '…' | --payload file.json", file=sys.stderr)
        return 2
    out = run_prompt(api_key, prompt, wait=True)
    print(out["reply"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
