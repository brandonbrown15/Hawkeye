# Hawkeye web research

Hawkeye can look up engineering facts, docs, and options on the web, cite sources in chat, and optionally seed Notion tasks.

## Triggers

Research runs when the operator message looks like a lookup, including:

- `research …`, `look up …`, `search the web …`
- `find docs`, `datasheet`, `compare options`, `latest …`
- `/research <query>` or `research: <query>`

Force always-on with `HAWKEYE_RESEARCH_ALWAYS=1` (noisy; not recommended).

## Providers

1. **Brave Search API** — if `BRAVE_SEARCH_API_KEY` is set  
2. **DuckDuckGo HTML** — default, no key  

## Env

| Key | Default | Meaning |
|-----|---------|---------|
| `HAWKEYE_RESEARCH_ENABLED` | `1` | Master switch |
| `HAWKEYE_RESEARCH_TOP_K` | `5` | Max sources |
| `BRAVE_SEARCH_API_KEY` | _(empty)_ | Preferred provider |

## Notion seeding

If the message also asks to `seed notion` / `create task` / `file a task`, sources are attached to a new Build Queue checklist item via the existing self-feed helper.

## Privacy

- Research results may be stored in **private** Hawkeye memory (`kind=research`).
- Do not paste research transcripts into public Autocode.
- Prefer tunnel-only UI exposure so research replies stay behind login.
