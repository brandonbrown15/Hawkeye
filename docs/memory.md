# Hawkeye vector memory (4TB SSD)

Personal conversational + decision memory stays on the Jetson data SSD. It must **never** be copied into public Autocode.

## Layout

```
$AUTOCODE_DATA_ROOT/hawkeye/memory/memories.jsonl
```

Override with `HAWKEYE_MEMORY_DIR`. Dev / cloud agents fall back to `state/hawkeye-memory/`.

Bootstrap creates the directory:

```bash
./bootstrap/05_use_data_ssd.sh
```

## How it works

1. Each UI chat turn is embedded (Ollama `nomic-embed-text` when available; otherwise a deterministic hash embed).
2. Records append to `memories.jsonl` with metadata (`kind`, provider, escalated flag).
3. Before answering, Hawkeye retrieves top-k similar memories and injects them into the system prompt.
4. Optional `HAWKEYE_MEMORY_KEY` encrypts each line at rest (HMAC + keystream). See [security.md](security.md).

## Env

| Key | Default | Meaning |
|-----|---------|---------|
| `HAWKEYE_MEMORY_ENABLED` | `1` | Master switch |
| `HAWKEYE_MEMORY_DIR` | `$AUTOCODE_DATA_ROOT/hawkeye/memory` | Store root |
| `HAWKEYE_MEMORY_TOP_K` | `5` | Retrieval count |
| `HAWKEYE_EMBED_MODEL` | `nomic-embed-text` | Ollama embed model |
| `HAWKEYE_EMBED_FORCE_HASH` | `0` | Skip Ollama (tests) |
| `HAWKEYE_MEMORY_KEY` | _(empty)_ | Passphrase / hex for at-rest encryption |

## API

- `GET /api/memory` — store stats (private session required)
- Chat responses include `memory_id` and `memory_hits`

## Privacy boundary

| Allowed | Forbidden |
|---------|-----------|
| Private Hawkeye repo runtime on Jetson | Committing `memories.jsonl` |
| Encrypted SSD path | Syncing memory into Autocode PRs |
| Operator-visible `/api/memory` stats | Pasting personal transcripts into public Notion |

Pull `nomic-embed-text` on the Jetson for better recall:

```bash
ollama pull nomic-embed-text
```
