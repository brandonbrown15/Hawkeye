# Notion setup (bring your own workspace)

Autocode does **not** ship with anyone else's Notion IDs or tokens.

## Fully automatic (recommended)

1. Create an internal integration at [Notion → My integrations](https://www.notion.so/my-integrations).
2. Copy the secret → `NOTION_TOKEN` in `.env`.
3. Create an **empty page** (e.g. “Autocode Hub”), open **··· → Connections**, add the integration.
4. Copy the page id from the URL → `NOTION_HUB_PAGE` in `.env`.
5. Run:

```bash
python3 notion/client.py provision --seed
# or the full Jetson path:
./scripts/go_live.sh --local-only
```

That creates **Build Queue**, **Agent Runs**, and **Escalation Log** under the hub page, writes the DB ids into `.env` + `notion/ids.yaml`, and seeds one **Ready + Local-safe** task.

Re-running `provision` reuses existing DBs with the same titles (idempotent).

## Manual schema (if you prefer hand-built DBs)

### Build Queue

| Property | Type | Notes |
|----------|------|--------|
| Name | Title | Task title |
| Status | Select | `Backlog`, `Ready`, `Running`, `Needs review`, `Done`, `Blocked` |
| Priority | Select | `P0`–`P3` |
| Complexity | Select | `Local-safe`, `Maybe local`, `Cloud-only` |
| Model route | Select | `Local Hermes`, `Claude`, `Grok`, `Cursor Cloud` |
| Repo | Text | Which git repo to work in |
| Acceptance | Text | Definition of done |
| Branch / PR | URL | Filled by autopilot |
| Notes | Text | Optional |
| Task ID | ID | Optional (`BLD` prefix) |

### Agent Runs

| Property | Type | Notes |
|----------|------|--------|
| Name | Title | Run label |
| Outcome | Select | `Success`, `Partial`, `Failed`, `Escalated`, `Skipped` |
| Model used | Select | `Local`, `Claude`, `Grok`, `Cursor`, `Mixed` |
| Summary | Text | What happened |
| PR / commit | URL | Optional |

### Escalation Log

| Property | Type | Notes |
|----------|------|--------|
| Name | Title | Task / failure label |
| Status | Select | `Open`, `Assigned`, `Resolved` |
| Why escalated | Select | `Too complex`, `Tool fail`, `Tests failing`, `Needs secrets`, `Ambiguous` |
| Send to | Select | `Claude`, `Grok Bot`, `Cursor Cloud`, `Human` |
| Context | Text | Branch + failure notes |
| Related PR | URL | Optional |

Share each DB with the integration, then set:

```bash
NOTION_BUILD_QUEUE_DB=...
NOTION_AGENT_RUNS_DB=...
NOTION_ESCALATION_LOG_DB=...
```

## Smoke test

```bash
python3 notion/client.py doctor
python3 notion/client.py list-ready
```
