# Hawkeye team PM (Notion backend)

Hawkeye’s main UI is a **project board** that reads your Notion databases.

## Boards

| Tab in Hawkeye | Notion database | Env override |
|----------------|-----------------|--------------|
| Hawkeye | Hawkeye Build Queue | `NOTION_BUILD_QUEUE_DB` |
| ROSE Projects | ROSE Projects | `NOTION_ROSE_PROJECTS_DB` |
| Autocode / Coding Machine | LCM Build Queue | `NOTION_LCM_BUILD_QUEUE_DB` |

Default database IDs for BrownHawke are built in when `HAWKEYE_NOTION_USE_DEFAULTS=1`.

## API

```
GET  /api/projects
GET  /api/tasks?board=hawkeye&status=Ready&limit=50
GET  /api/tasks/{page_id}?board=hawkeye
POST /api/tasks            { "name": "…", "status": "Ready", "priority": "P2", "token": "…" }
POST /api/tasks/{page_id}   { "status": "Done", "token": "…" }
```

The web UI defaults to a **queue list** with an add-task field. Kanban remains available as Board. Chat can still create cards (`add a Ready task: …`).

Without `NOTION_TOKEN`, the UI shows sample tasks and a banner. Connect Notion on the Jetson:

```bash
./scripts/connect_notion.sh
# ensure the integration is shared on the Hawkeye Build Queue + ROSE Projects DBs
```

## Chat PM commands

Talk to Hawkeye (UI chat). These hit Notion through `notion/pm.py` and **do not** go to Cursor or Grok:

| You say | Hawkeye does |
|---------|----------------|
| `what's on the Hawkeye board?` | Lists open Hawkeye Build Queue cards |
| `show open P0/P1` | Same board, open P0 and P1 only |
| `show the ROSE board` | Lists open ROSE project cards |
| `mark HK-12 Done` | Writes Status = Done |
| `set HK-12 to Ready` | Writes Status = Ready |
| `add a Ready task: …` | Creates a Ready card (optional `add a P1 Ready task: …`) |

After a useful board answer or status change, Hawkeye stores a short summary with `memory.remember_decision` so later chat turns can recall it.

Cursor escalate is unchanged: architecture / repo-review asks still go to Cursor when configured. Grok Bot webhook is not required for PM commands.

## Team workflow

1. Plan / track work in Notion, or ask Hawkeye chat (`add a Ready task: …`).
2. View the same tasks as a kanban in Hawkeye.
3. Update status from the task drawer **or** chat (`mark HK-xx Done`).
4. Autopilot / chat remain available under **Autopilot controls**.
