"""Host / Jetson performance snapshot for the chat header strip.

Reads local sysfs and /proc only — no fake numbers. Missing sensors
are omitted so the UI can show an em dash.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

_CPU_PREV: tuple[int, int] | None = None


def reset_cpu_sample() -> None:
    global _CPU_PREV
    _CPU_PREV = None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _cpu_times() -> tuple[int, int] | None:
    raw = _read_text(Path("/proc/stat"))
    if not raw:
        return None
    first = raw.splitlines()[0]
    parts = first.split()
    if not parts or parts[0] != "cpu" or len(parts) < 5:
        return None
    nums = [int(x) for x in parts[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    total = sum(nums)
    return idle, total


def cpu_pct() -> float | None:
    """Utilization since the previous sample (None on first call)."""
    global _CPU_PREV
    now = _cpu_times()
    if not now:
        return None
    prev = _CPU_PREV
    _CPU_PREV = now
    if not prev:
        return None
    d_idle = now[0] - prev[0]
    d_total = now[1] - prev[1]
    if d_total <= 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - (d_idle / d_total)) * 100.0)), 1)


def loadavg() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None


def ram_stats() -> dict[str, Any]:
    raw = _read_text(Path("/proc/meminfo"))
    if not raw:
        return {}
    kv: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        num = rest.strip().split()[0]
        try:
            kv[key] = int(num)
        except ValueError:
            continue
    total = kv.get("MemTotal")
    avail = kv.get("MemAvailable") or kv.get("MemFree")
    if not total:
        return {}
    used = total - (avail or 0)
    return {
        "ram_total_mb": round(total / 1024),
        "ram_used_mb": round(used / 1024),
        "ram_pct": round(used / total * 100.0, 1),
    }


def gpu_pct() -> tuple[float | None, str | None]:
    """Return (percent, source). Jetson sysfs first, then nvidia-smi."""
    jetson = Path("/sys/devices/gpu.0/load")
    raw = _read_text(jetson)
    if raw and raw.isdigit():
        # Jetson reports tenths of a percent (0–1000).
        return round(int(raw) / 10.0, 1), "jetson"
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=0.6,
            ).strip()
            first = out.splitlines()[0].strip()
            return float(first), "nvidia-smi"
        except (subprocess.SubprocessError, ValueError, OSError):
            return None, None
    return None, None


def temp_c() -> float | None:
    thermal = Path("/sys/class/thermal")
    if not thermal.is_dir():
        return None
    best: float | None = None
    for zone in sorted(thermal.glob("thermal_zone*/temp")):
        raw = _read_text(zone)
        if not raw:
            continue
        try:
            milli = int(raw)
        except ValueError:
            continue
        if milli < 1000:
            continue
        celsius = milli / 1000.0
        if 0 < celsius < 120 and (best is None or celsius > best):
            best = celsius
    return round(best, 1) if best is not None else None


def ollama_status() -> dict[str, Any]:
    """Live Ollama process list — up/idle/loaded model. Never invent a load %."""
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").strip() or "127.0.0.1:11434"
    try:
        import json
        import urllib.request

        req = urllib.request.Request(f"http://{host}/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("models") if isinstance(data, dict) else None
        names = []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
        return {
            "ollama_up": True,
            "ollama_model": names[0] if names else "",
            "ollama_loaded": len(names),
        }
    except Exception:  # noqa: BLE001
        return {"ollama_up": False, "ollama_model": "", "ollama_loaded": 0}


def snapshot() -> dict[str, Any]:
    gpu, gpu_src = gpu_pct()
    out: dict[str, Any] = {
        "ok": True,
        "cpu_pct": cpu_pct(),
        "load1": loadavg(),
        "nproc": os.cpu_count(),
        "gpu_pct": gpu,
        "gpu_source": gpu_src,
        "temp_c": temp_c(),
        "ts": int(time.time()),
    }
    out.update(ram_stats())
    out.update(ollama_status())
    return out
