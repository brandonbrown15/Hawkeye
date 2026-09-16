#!/usr/bin/env python3
"""Detect and run lightweight repo checks after a local coding turn."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_repo_checks(repo_dir: Path, timeout_sec: int = 600) -> tuple[bool, str]:
    """Return (ok, log). Skip gracefully when no known check exists."""
    commands: list[list[str]] = []
    if (repo_dir / "package.json").exists():
        pkg = (repo_dir / "package.json").read_text(errors="ignore")
        if '"test"' in pkg:
            commands.append(["npm", "test", "--silent"])
        if '"lint"' in pkg:
            commands.append(["npm", "run", "lint", "--silent"])
    if (repo_dir / "pyproject.toml").exists() or (repo_dir / "pytest.ini").exists():
        commands.append(["python3", "-m", "pytest", "-q"])
    elif list(repo_dir.glob("**/test_*.py")) or list(repo_dir.glob("**/tests")):
        commands.append(["python3", "-m", "pytest", "-q"])
    if (repo_dir / "Cargo.toml").exists():
        commands.append(["cargo", "test", "--quiet"])
    if (repo_dir / "go.mod").exists():
        commands.append(["go", "test", "./..."])

    if not commands:
        return True, "no automated checks detected — skipped"

    logs: list[str] = []
    for cmd in commands:
        if not shutil_which(cmd[0]):
            logs.append(f"skip {' '.join(cmd)} (binary missing)")
            continue
        proc = subprocess.run(
            cmd, cwd=repo_dir, capture_output=True, text=True, timeout=timeout_sec
        )
        logs.append(f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{proc.stdout[-1000:]}\n{proc.stderr[-1000:]}")
        if proc.returncode != 0:
            return False, "\n".join(logs)
    return True, "\n".join(logs)


def shutil_which(name: str) -> bool:
    from shutil import which

    return which(name) is not None
