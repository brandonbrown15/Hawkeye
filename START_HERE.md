# START HERE

## One command (Hawkeye / Jetson)

```bash
git clone https://github.com/brandonbrown15/Hawkeye.git ~/Hawkeye
cd ~/Hawkeye
./start
```

If you see `Permission denied` under `/opt`, clone to `~/Hawkeye` instead (no sudo).

Answer a few questions. Wait. Done.

Full details: **[README.md](README.md)** · private deploy: **[docs/hawkeye.md](docs/hawkeye.md)**

---

## What you need before `./start`

1. **GitHub access** to private `brandonbrown15/Hawkeye`  
2. **Notion** — internal integration (or OAuth) shared on **Hawkeye Build Queue** (+ ROSE Projects if used)  
3. **This computer on** (Jetson Orin Nano Super recommended)  
4. Optional: **4TB NVMe** — `./start` / bootstrap will park models, swap, and memory there  
5. Optional: **Cloudflare** for `hawkeye.brownhawke.engineering` (Tunnel + DNS)

---

## After setup

| Do this | Command |
|---------|---------|
| Open the dashboard | `./scripts/ui.sh` → http://127.0.0.1:8787/ |
| Start on every boot | `./scripts/install_hawkeye_autostart.sh` |
| Recreate local coder | `./ollama/create_coder_64k.sh` |
| Better chat memory | `ollama pull nomic-embed-text` |
| Remote phone view | `./scripts/ui.sh --remote` (Tailscale) |
| Public HTTPS | Cloudflare Tunnel (see README §7) |
| Project autopilot | `AUTOCODE_AUTOPILOT_ENABLED=1` + `./cron/install_autopilot_timers.sh` |
| Health | `./scripts/doctor.sh` |
| Pause | `./scripts/control.sh pause` |
| Add work | Notion → Hawkeye Build Queue → Status = **Ready** |

Login: work emails `@brownhawke.engineering` only (`config/users.json`).

---

## Stuck?

```bash
./scripts/doctor.sh
```

Read the **FAIL** lines. Fix those. Run `./start` or `./scripts/bootstrap_jetson.sh` again.

More: [docs/go-live.md](docs/go-live.md) · [docs/jetson.md](docs/jetson.md) · [docs/pm.md](docs/pm.md)
