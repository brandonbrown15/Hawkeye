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
POST /api/tasks/{page_id}   { "status": "Done", "token": "…" }
```

Without `NOTION_TOKEN`, the UI shows sample tasks and a banner. Connect Notion on the Jetson:

```bash
./scripts/connect_notion.sh
# ensure the integration is shared on the Hawkeye Build Queue + ROSE Projects DBs
```

## Team workflow

1. Plan / track work in Notion (or create via Hawkeye chat “seed Notion”).
2. View the same tasks as a kanban in Hawkeye.
3. Update status from the task drawer (writes back to Notion).
4. Autopilot / chat remain available under **Autopilot controls**.
