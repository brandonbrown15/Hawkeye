# Hawkeye web research (deep page read)

Hawkeye looks up engineering facts, docs, and options on the web, **reads the top result pages**, cites sources in chat, and optionally seeds Notion tasks.

## Triggers

Research runs when the operator message looks like a lookup, including:

- `research …`, `look up …`, `search the web …`, `search for …`
- `deep research …`, `deep search …`, `thorough research …`
- `find docs`, `datasheet`, `compare options`, `latest …`
- `/research <query>` or `research: <query>`
- a bare `search …` verb (so chat actually invokes the tool)

Force always-on with `HAWKEYE_RESEARCH_ALWAYS=1` (noisy; not recommended).

## Local only vs Brave Search

**Local only** (header switch, per account) means **no external web**: no Brave, no DuckDuckGo, no page fetches. Cloud escalate (Cursor/Grok) is also off.

| Local only | Brave key (Connections or `BRAVE_SEARCH_API_KEY`) | Chat web search |
|------------|---------------------------------------------------|-----------------|
| On | any | Blocked. UI hints “Web search needs Local only off.” |
| Off | configured | Brave Search runs when the operator asks |
| Off | missing | DuckDuckGo HTML fallback |

If Brave is connected and Local only is **off**, Hawkeye must not claim it has “no internet.” Interactive chat calls Brave in **snippet-fast** mode (no page fetches) unless the operator says `deep research` / `go deep`, so the 25s UI timeout does not abort before results land. The host injects Brave results into the system prompt and rewrites replies that still deny web access. The chat badge shows **Hawkeye · Brave** (or **Brave ready**), not **Local · Jetson**.

The research checklist item stays optional (`HAWKEYE_RESEARCH_ENABLED`). The key itself is preferred from **Account → Connections → Brave**, then machine `.env`.

## Depth

Default **deep mode** (`HAWKEYE_RESEARCH_DEEP=1`):

1. SERP via Brave or DuckDuckGo  
2. Fetch top `HAWKEYE_RESEARCH_FETCH_MAX` pages and extract readable text  
3. If results are weak, one reformulation pass (docs-oriented query)

Snippet-only mode: set `HAWKEYE_RESEARCH_DEEP=0`.

## Providers

1. **Brave Search API** — if `BRAVE_SEARCH_API_KEY` is set  
2. **DuckDuckGo HTML** — default, no key  

## Env

| Key | Default | Meaning |
|-----|---------|---------|
| `HAWKEYE_RESEARCH_ENABLED` | `1` | Master switch |
| `HAWKEYE_RESEARCH_DEEP` | `1` | Fetch and read result pages |
| `HAWKEYE_RESEARCH_TOP_K` | `5` | Max SERP sources |
| `HAWKEYE_RESEARCH_FETCH_MAX` | `3` | Pages to download in deep mode |
| `HAWKEYE_RESEARCH_FETCH_BYTES` | `200000` | Max bytes per page |
| `HAWKEYE_RESEARCH_FETCH_TIMEOUT` | `12` | Seconds per page fetch |
| `HAWKEYE_RESEARCH_EXCERPT_CHARS` | `4000` | Max chars kept per page |
| `HAWKEYE_RESEARCH_MAX_ROUNDS` | `2` | Allow one reformulation when weak |
| `BRAVE_SEARCH_API_KEY` | _(empty)_ | Preferred SERP provider |

## Notion seeding

If the message also asks to `seed notion` / `create task` / `file a task`, sources are attached to a new Build Queue checklist item via the existing self-feed helper.

## Privacy

- Research results may be stored in **private** Hawkeye memory (`kind=research`).
- Do not paste research transcripts into public Autocode.
- Prefer tunnel-only UI exposure so research replies stay behind login.
- Page fetches use a polite User-Agent; keep volume modest on shared Jetsons.
