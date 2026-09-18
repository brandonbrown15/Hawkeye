# How Autocode decides local vs cloud

Autocode runs **independently overnight** and picks the **cheapest effective path** for each task.

```text
Ready task
   │
   ├─ score task (Complexity + Priority + keywords + Model route)
   │
   ├─ score < 30  → local Hermes (Jetson / Ollama)
   ├─ score 30–49 → light cloud   (ladder slot 0)
   ├─ score 50–69 → mid cloud     (ladder slot 1)
   ├─ score 70+   → heavy cloud   (prefer Cursor capability)
   │
   ├─ hardware / Hermes / Ollama unhealthy → same tier
   └─ Notion Model route set explicitly → that target wins
```

## Cost research ranking (2026)

Sticker $/MTok is misleading for overnight **agent loops** (big prompts + many tool turns). Effective spend rank:

| Rank (cheapest →) | Path | Why |
|-------------------|------|-----|
| 1 | **Local Hermes** | Free compute on Jetson |
| 2 | **Cursor Ultra** (~$200/mo) | Flat pool; **Grok 4.5/4.6 included** in Cursor Models + ~$400 Other Models |
| 3 | **Claude Max / Claude Code** ($100–200/mo) | Flat subscription; optional if you already pay Ultra |
| 4 | **Claude API** (Sonnet ~$2/$10 per MTok) | Metered; OK for occasional mid jobs |
| 5 | **Direct xAI Grok API** ($2/$6, doubles past ~200k context) | **Often the worst** for agents — uncapped; $80/day is easy |

**Recommendation:** Cursor Ultra + your **Grok Bot** webhook (flat SuperGrok / Telegram bot). Leave `XAI_API_KEY` empty overnight. Autocode picks the cheaper configured cloud first.

```bash
# .env (local only) — Cursor Ultra + Grok Bot, cheaper first
AUTOCODE_COST_PROFILE=cursor-grok
AUTOCODE_CLOUD_PREFERENCE=cursor    # or grok if Bot is cheaper for you
AUTOCODE_CURSOR_DELEGATE_CMD=./scripts/delegate_cursor.sh
AUTOCODE_GROK_DELEGATE_CMD=./scripts/delegate_grok.sh
CURSOR_API_KEY=…                    # Dashboard → API Keys (required for live Cursor)
CURSOR_REPOSITORY=https://github.com/brandonbrown15/Hawkeye  # optional
# CURSOR_WEBHOOK_URL=https://…      # optional custom bridge only
GROK_BOT_WEBHOOK_URL=https://…      # required for live Grok Bot handoff
AUTOCODE_DISABLE_METERED_GROK=1
# Leave empty:
# XAI_API_KEY=
# ANTHROPIC_API_KEY=
```

### Profiles

| Profile | Ladder | Use when |
|---------|--------|----------|
| **`cursor-grok`** | **Cursor → Grok Bot → Human** | **Ultra + Bot (recommended)** |
| `cursor-ultra` | Cursor Cloud → Human | Ultra only |
| `claude-max` | Claude → Cursor → Human | Keeping Claude Max |
| `metered` | Claude → Cursor → Grok Bot → Human | Pure API keys |
| `default` | same as `cursor-grok` | Mixed Cursor + Bot |

`AUTOCODE_CLOUD_PREFERENCE=grok` swaps Bot ahead of Cursor when your Bot plan is flatter.

```bash
AUTOCODE_COST_PROFILE=cursor-grok
# or fully custom:
AUTOCODE_COST_LADDER=Cursor Cloud,Grok Bot,Human
```

## Tier → target (`cursor-grok`)

| Tier | Target |
|------|--------|
| local | Local Hermes |
| cheap | Cursor Cloud (Ultra pool — usually cheaper) |
| standard (mid) | Grok Bot (your webhook / SuperGrok agent) |
| premium | Cursor Cloud (capability preference) |
| human | Human |

See [go-live.md](go-live.md) for the operator checklist.

## Local path

1. Claim task (`Status = Running`)
2. Health-check Hermes + Ollama (else escalate to scored tier)
3. Create branch `hermes/<task-id>-slug`
4. Run Hermes against local Ollama (up to `AUTOCODE_MAX_LOCAL_ATTEMPTS`)
5. Run detected repo checks
6. Open PR with `gh` when possible
7. Mark **Needs review** + log **Agent Runs**

## Escalation / delegation

Writes **Escalation Log** + JSON under `state/delegates/`.

| Target | Config |
|--------|--------|
| Cursor Cloud | `AUTOCODE_CURSOR_DELEGATE_CMD` / `CURSOR_API_KEY` — preferred cloud path on Ultra |
| Claude | `ANTHROPIC_API_KEY` — mid on `default` / `claude-max` |
| Grok Bot | **Avoid metered** — only if on ladder/`metered` profile; `AUTOCODE_GROK_DELEGATE_CMD` → `XAI_API_KEY` → `OPENROUTER_API_KEY` |
| Human | no cloud keys |

### Grok Bot (metered — use sparingly)

Direct xAI/OpenRouter Grok is tried only when the ladder includes **Grok Bot** and `AUTOCODE_DISABLE_METERED_GROK` is unset. Prefer Cursor Ultra’s included Grok instead.

## Scoring cheat sheet

| Signal | Approx. points |
|--------|----------------|
| Local-safe | +10 |
| Maybe local | +40 |
| Cloud-only | +55 (mid floor; not auto-premium) |
| P0 / P1 / P2 | +25 / +15 / +5 |
| Heavy keywords (auth, billing, k8s, …) | +10 each, capped +30 |
| Explicit Model route ≠ Local | floor 55 (mid+) |

## Hardware thresholds (defaults)

Escalate instead of thrashing locally when MemAvailable / disk / load cross limits. Escalation still respects the cost profile (light tasks do not jump to metered Grok).
