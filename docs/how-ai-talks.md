# How Autocode’s AI layers talk

Short version: **Hermes only talks to your local Ollama.**  
Everything else (Cursor, Grok Bot, Claude) is called by the **orchestrator**, not by Hermes.

```text
Notion Build Queue (Ready tasks)
        │
        ▼
 orchestrator/run_night.py     ← night boss / traffic cop
        │
        ├─ easy task ──► Hermes CLI ──► local Ollama (coder-64k)
        │                    │
        │                    └─ edits repo → checks → GitHub PR
        │
        └─ hard / failed local ──► escalate
                 │
                 ├─ Cursor Cloud   (Cloud Agents API / optional webhook)
                 ├─ Grok Bot       (webhook JSON POST)
                 ├─ Claude API     (direct HTTPS, optional)
                 └─ Human          (Notion Escalation Log)
```

## Local path (cheap / free)

1. Cron runs `cron/overnight_run.sh` → `orchestrator/run_night.py`
2. Orchestrator scores the Notion task (`orchestrator/policy.py`)
3. If “local-safe”, it runs: `hermes chat -q "<task prompt>"`
4. Hermes is configured (by `hermes/configure_local_primary.sh`) to use  
   `http://127.0.0.1:11434/v1` = **Ollama**
5. Hermes edits files with tools; orchestrator runs checks and opens a PR

Hermes does **not** call Cursor or Grok. It only sees local Ollama.

## Cloud path (when local isn’t enough)

If the task is hard, cloud-only, or local Hermes fails twice:

1. Orchestrator writes a JSON handoff file under `state/delegates/`
2. It launches Cursor via the **Cloud Agents API** when `CURSOR_API_KEY` is set
   (`integrations/cursor_cloud.py` → `POST https://api.cursor.com/v1/agents`),
   or runs a shell command with `AUTOCODE_DELEGATE_PAYLOAD`:
   - Cursor → `scripts/delegate_cursor.sh` (API key preferred, else webhook bridge)
   - Grok Bot → `scripts/delegate_grok.sh` → `POST $GROK_BOT_WEBHOOK_URL`
   - Claude → Anthropic HTTP API (if `ANTHROPIC_API_KEY` set)
3. Result is logged back to Notion (Agent Runs / Escalation Log)

## Cost ladder (default `cursor-grok`)

| Prefer first | Who | How |
|--------------|-----|-----|
| 1 | Local Hermes + Ollama | CLI |
| 2 | Cursor Cloud | API (`CURSOR_API_KEY`) |
| 3 | Grok Bot | webhook |
| 4 | Human | Notion only |

Metered raw `XAI_API_KEY` stays off overnight by default (`AUTOCODE_DISABLE_METERED_GROK=1`).

## Mental model

Think of Hermes as the **on-device worker**.  
Think of the orchestrator as the **foreman** who decides when to call expensive outside help.
