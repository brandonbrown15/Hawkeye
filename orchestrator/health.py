#!/usr/bin/env python3
"""Local runtime health checks for Autocode."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class HealthReport:
    hermes_ok: bool
    ollama_ok: bool
    ollama_model: str
    details: list[str]

    @property
    def local_ready(self) -> bool:
        return self.hermes_ok and self.ollama_ok


def check_local_stack() -> HealthReport:
    details: list[str] = []
    hermes_ok = shutil.which("hermes") is not None
    details.append("hermes: present" if hermes_ok else "hermes: MISSING")

    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "coder-64k")
    ollama_ok = False
    try:
        with urllib.request.urlopen(f"http://{host}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        names = {m.get("name", "") for m in data.get("models", [])}
        # Exact or prefix match (coder-64k / coder-64k:latest)
        ollama_ok = any(model == n or n.startswith(model + ":") or n.startswith(model) for n in names) or (
            bool(names) and model == "coder-64k" and any("coder" in n for n in names)
        )
        if ollama_ok:
            details.append(f"ollama: ok ({host}), model={model}")
        else:
            details.append(f"ollama: reachable but model {model!r} not found in {sorted(names)[:8]}")
            # Still allow if server up — Hermes may pull
            ollama_ok = True
            details.append("ollama: treating as ok (server up; ensure model pulled)")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        details.append(f"ollama: DOWN ({e})")

    return HealthReport(hermes_ok=hermes_ok, ollama_ok=ollama_ok, ollama_model=model, details=details)
