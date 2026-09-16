"""SSD-backed conversational / decision memory for Hawkeye."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from memory import crypto, embed


@dataclass
class MemoryHit:
    id: str
    kind: str
    text: str
    score: float
    meta: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


@dataclass
class MemoryRecord:
    id: str
    kind: str
    text: str
    embedding: list[float]
    meta: dict[str, Any]
    ts: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or "note"),
            text=str(data.get("text") or ""),
            embedding=[float(x) for x in (data.get("embedding") or [])],
            meta=dict(data.get("meta") or {}),
            ts=float(data.get("ts") or 0.0),
        )


def default_memory_root() -> Path:
    """Prefer 4TB SSD data root; fall back to repo-local state (dev only)."""
    explicit = os.environ.get("HAWKEYE_MEMORY_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    data = os.environ.get("AUTOCODE_DATA_ROOT", "").strip()
    if data:
        return Path(data).expanduser() / "hawkeye" / "memory"
    # Dev / cloud agent fallback — never used on Jetson once SSD bootstrap runs.
    return Path(os.environ.get("AUTOCODE_STATE_DIR", "state")).expanduser() / "hawkeye-memory"


class MemoryStore:
    """Append-only JSONL vector store with cosine retrieval."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_memory_root()
        self.path = self.root / "memories.jsonl"
        self._lock = threading.Lock()
        self._cache: list[MemoryRecord] | None = None

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def remember(
        self,
        text: str,
        *,
        kind: str = "chat",
        meta: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryRecord:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty memory text")
        self.ensure()
        rec = MemoryRecord(
            id=uuid.uuid4().hex,
            kind=kind,
            text=text,
            embedding=embedding if embedding is not None else embed.embed(text),
            meta=dict(meta or {}),
            ts=time.time(),
        )
        line = crypto.encode_record(rec.to_dict())
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if self._cache is not None:
                self._cache.append(rec)
        return rec

    def remember_turn(
        self,
        user: str,
        assistant: str,
        *,
        provider: str = "local",
        escalated: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> MemoryRecord | None:
        user = (user or "").strip()
        assistant = (assistant or "").strip()
        if not user and not assistant:
            return None
        blob = f"User: {user}\nAssistant ({provider}): {assistant}".strip()
        meta = {"provider": provider, "escalated": escalated}
        if extra:
            meta.update(extra)
        return self.remember(blob, kind="chat", meta=meta)

    def remember_decision(self, decision: str, *, meta: dict[str, Any] | None = None) -> MemoryRecord:
        return self.remember(decision, kind="decision", meta=meta)

    def load(self, *, reload: bool = False) -> list[MemoryRecord]:
        with self._lock:
            if self._cache is not None and not reload:
                return list(self._cache)
            self.ensure()
            records: list[MemoryRecord] = []
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(MemoryRecord.from_dict(crypto.decode_record(line)))
                except (ValueError, KeyError, TypeError):
                    continue
            self._cache = records
            return list(records)

    def search(self, query: str, *, limit: int = 5, min_score: float = 0.15) -> list[MemoryHit]:
        query = (query or "").strip()
        if not query:
            return []
        q = embed.embed(query)
        hits: list[MemoryHit] = []
        for rec in self.load():
            if not rec.embedding:
                continue
            # Hash embed dim may differ from Ollama; compare on shared prefix.
            score = embed.cosine(q, rec.embedding)
            if score < min_score:
                continue
            hits.append(
                MemoryHit(
                    id=rec.id,
                    kind=rec.kind,
                    text=rec.text,
                    score=score,
                    meta=rec.meta,
                    ts=rec.ts,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: max(0, limit)]

    def format_for_prompt(self, query: str, *, limit: int = 5) -> str:
        hits = self.search(query, limit=limit)
        if not hits:
            return ""
        lines = ["Relevant Hawkeye memory (private — do not invent beyond this):"]
        for i, hit in enumerate(hits, 1):
            snippet = hit.text.replace("\n", " ").strip()
            if len(snippet) > 400:
                snippet = snippet[:397] + "..."
            lines.append(f"{i}. [{hit.kind} · {hit.score:.2f}] {snippet}")
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        records = self.load()
        by_kind: dict[str, int] = {}
        for rec in records:
            by_kind[rec.kind] = by_kind.get(rec.kind, 0) + 1
        return {
            "root": str(self.root),
            "path": str(self.path),
            "count": len(records),
            "by_kind": by_kind,
            "encrypted": bool(crypto.memory_key()),
        }


_STORE: MemoryStore | None = None


def get_store() -> MemoryStore:
    global _STORE
    if _STORE is None:
        _STORE = MemoryStore()
    return _STORE


def reset_store_for_tests(root: Path | None = None) -> MemoryStore:
    """Replace the process-global store (tests only)."""
    global _STORE
    _STORE = MemoryStore(root=root)
    return _STORE
