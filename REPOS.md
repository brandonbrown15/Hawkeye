# Two repositories

| Repo | Visibility | Product | Purpose |
|------|------------|---------|---------|
| **Autocode** | Public · https://github.com/brandonbrown15/Autocode | Autocode | Open-source Notion/Jetson coding autopilot (Apache-2.0) |
| **Hawkeye** | **Private** · https://github.com/brandonbrown15/Hawkeye | Hawkeye | Personal fork: login, domain, free local LLM, Cursor/Grok escalate · **proprietary** |

Do **not** merge Hawkeye-only config (password hashes, personal domains, webhook URLs) into Autocode `main`.

```bash
./scripts/publish_hawkeye_private.sh https://github.com/brandonbrown15/Hawkeye.git
```

Details: [docs/hawkeye.md](docs/hawkeye.md)
