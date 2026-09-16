"""Text → embedding vectors.

Prefer Ollama `/api/embeddings` when available. Fall back to a deterministic
local hash embedding so unit tests and offline Jetson boots still work.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Sequence


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def embed_dim() -> int:
    return int(os.environ.get("HAWKEYE_EMBED_DIM", "384") or "384")


def embed_model() -> str:
    return os.environ.get("HAWKEYE_EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text"


def hash_embed(text: str, dim: int | None = None) -> list[float]:
    """Deterministic bag-of-tokens embedding (no network). Good enough for tests."""
    d = dim or embed_dim()
    vec = [0.0] * d
    tokens = (text or "").lower().split()
    if not tokens:
        tokens = ["_empty_"]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        # Spread each token across a few dimensions.
        for i in range(0, 16, 4):
            idx = int.from_bytes(digest[i : i + 2], "big") % d
            sign = 1.0 if digest[i + 2] % 2 == 0 else -1.0
            mag = (digest[i + 3] + 1) / 256.0
            vec[idx] += sign * mag
    return _l2_normalize(vec)


def ollama_embed(text: str) -> list[float] | None:
    """Call Ollama embeddings API. Returns None on failure."""
    if _env_truthy("HAWKEYE_EMBED_FORCE_HASH"):
        return None
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    model = embed_model()
    body = json.dumps({"model": model, "prompt": text}).encode()
    req = urllib.request.Request(
        f"http://{host}/api/embeddings",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("HAWKEYE_EMBED_TIMEOUT", "30"))) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        return None
    try:
        return _l2_normalize([float(x) for x in emb])
    except (TypeError, ValueError):
        return None


def embed(text: str) -> list[float]:
    """Best available embedding for `text`."""
    remote = ollama_embed(text)
    if remote is not None:
        return remote
    return hash_embed(text)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0.0:
        return vec
    return [x / norm for x in vec]
