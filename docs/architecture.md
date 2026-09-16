# Architecture

```text
┌─────────────────────────────────────────────────────────┐
│  Your Notion workspace                                  │
│  Build Queue · Agent Runs · Escalation Log              │
└──────────────────────────▲──────────────────────────────┘
                           │ NOTION_TOKEN (local .env only)
┌──────────────────────────┴──────────────────────────────┐
│  Local AI box (Jetson Orin Nano Super or Linux + GPU)   │
│                                                         │
│  cron/overnight_run.sh                                  │
│       │                                                 │
│       ├─ notion/client.py  list-ready / claim / log     │
│       ├─ Hermes Agent + Ollama coder-64k (local)        │
│       ├─ git branch → tests → gh pr create              │
│       └─ scripts/send_telegram_digest.sh (optional)     │
└─────────────────────────────────────────────────────────┘
```

## Design goals

- **Local-first**: cheap/simple coding stays on-device
- **Escalation**: hard work goes to paid models or humans — no silent thrashing
- **Open config**: every operator brings their own Notion DBs, Telegram bot, and repos
- **No secrets in git**: `.env` and `notion/ids.yaml` are gitignored

## Suggested success metrics

- Share of coding turns handled locally (without paid APIs)
- ≥1 useful reviewable PR per overnight run on queued work
- Zero silent merges to `main`
