# Jetson Orin Nano Super notes

Target hardware for Autocode.

## Preferred: fully auto

```bash
# Mount your 4TB NVMe (example — adjust device/mount to match your box)
# sudo mkfs.ext4 /dev/nvme0n1p1   # only if blank
# sudo mkdir -p /mnt/nvme && sudo mount /dev/nvme0n1p1 /mnt/nvme
# echo '/dev/nvme0n1p1 /mnt/nvme ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab

export AUTOCODE_DATA_ROOT=/mnt/nvme/autocode   # optional override
./scripts/go_live.sh --local-only --first-night --enable-autopilot
```

`go_live` → `bootstrap_jetson` → `05_use_data_ssd.sh` parks **Ollama models, workspaces, logs, and swap** on the big disk so the eMMC/root does not fill up.

## One-shot bootstrap only

```bash
./scripts/bootstrap_jetson.sh
./scripts/doctor.sh
```

See [go-live.md](go-live.md).

## Phase 0 checklist

- [ ] Boots from NVMe **or** root on eMMC + 4TB data SSD mounted (e.g. `/mnt/nvme`)
- [ ] JetPack 6.x
- [ ] MAXN_SUPER via `nvpmodel` (`bootstrap/02_enable_maxn.sh`)
- [ ] Ethernet + SSH keys (+ optional Tailscale)
- [ ] `./bootstrap/05_use_data_ssd.sh` (sets `AUTOCODE_DATA_ROOT`, `OLLAMA_MODELS`, `WORKSPACE_ROOT`)
- [ ] 16G swap on the SSD (`sudo ./bootstrap/01_setup_swap.sh`)

## Phase 1 — local brain

- Jetson-capable Ollama / CUDA with `OLLAMA_MODELS` on the SSD
- Tool-capable 3B–7B coder (default Modelfile base: `qwen2.5-coder:7b` — smaller if VRAM forces it)
- `coder-64k` Modelfile with `num_ctx 65536`
- `OLLAMA_KEEP_ALIVE=24h`
- Smoke `/v1/chat/completions`
- Boot auto-start: `./scripts/install_hawkeye_autostart.sh` (UI + Ollama; tunnel when configured)

**Gotcha:** Ollama `/v1` often ignores per-request `num_ctx`. Prefer Modelfile `PARAMETER num_ctx`, `OLLAMA_CONTEXT_LENGTH`, and Hermes native `/api/chat`. Verify with `ollama ps`.

## Phase 2 — Hermes

- Primary = local `coder-64k`
- Smoke: `scripts/smoke_hermes.sh`
- Fallbacks only after local works

## Phase 3 — autopilot

- Notion provision (`notion/client.py provision --seed`) or `go_live.sh`
- Supervised night: `./cron/overnight_run.sh --force`
- `AUTOCODE_AUTOPILOT_ENABLED=1` + `cron/install_autopilot_timers.sh`
