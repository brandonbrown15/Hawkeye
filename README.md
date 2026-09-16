# Hawkeye

**Private** personal coding autopilot for BrownHawke — local Jetson LLM for free all-day use, with **Cursor** and **Grok Bot** taking over when a task is too hard. Login-gated UI on your own domain.

This is **not** the open-source Autocode repo. Autocode stays public; Hawkeye is your private fork.

Upstream (Apache-2.0, keep credit): [brandonbrown15/Autocode](https://github.com/brandonbrown15/Autocode)

## What you get

| Layer | Behavior |
|-------|----------|
| **Local Ollama** | Free all-day phone/laptop chat + easy Notion tasks |
| **Cursor / Grok Bot** | Escalate strenuous work (webhooks) |
| **Login** | Username/password session on the UI |
| **Domain** | Cloudflare Tunnel → `https://hawkeye.brownhawke.engineering` → Jetson UI |
| **Memory** | Vectorised chat/decisions on the 4TB SSD (`docs/memory.md`) |
| **Research** | Web lookup with citations (`docs/research.md`) |

## Setup

```bash
git clone https://github.com/brandonbrown15/Hawkeye.git
cd Hawkeye
./start
python3 scripts/set_private_password.py   # paste hash into .env
# set CURSOR_WEBHOOK_URL + GROK_BOT_WEBHOOK_URL in .env
./scripts/ui.sh
# Cloudflare Tunnel → https://hawkeye.brownhawke.engineering
```

Full personal deploy (domain + login + escalate): **[docs/hawkeye.md](docs/hawkeye.md)**

## License

**Proprietary** — BrownHawke Engineering. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Upstream Autocode (Apache-2.0) attribution is preserved in `NOTICE` and `LICENSE.Apache-2.0`. Keep this repository **private**; do not publish secrets (`.env`, webhooks, password hashes).
