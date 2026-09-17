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

## After bootstrap — fix common FAILs

**Order matters:** park data on SSD **before** creating models (or restart Ollama after).

```bash
# 1) Data root (NVMe or ~/autocode-data) — sets OLLAMA_MODELS
./bootstrap/05_use_data_ssd.sh
source .env   # or: export OLLAMA_MODELS=… from .env

# 2) Full Ollama install (CLI + llama-server JetPack runner) then create model
./ollama/install_ollama_jetson.sh
# If chat still says llama-server not found:
#   OLLAMA_FORCE_REINSTALL=1 ./ollama/install_ollama_jetson.sh
./ollama/ensure_ollama.sh --restart
./ollama/create_coder_64k.sh
# Orin Nano CUDA OOM on 7B → script defaults to qwen2.5-coder:3b.
# Manual: BASE_MODEL=qwen2.5-coder:3b OLLAMA_NUM_CTX=8192 ./ollama/create_coder_64k.sh
# Prove: ollama run coder-64k OK
# Optional free disk: ollama rm qwen2.5-coder:7b

# 3) Hermes config (writes under HERMES_CONFIG_DIR from .env)
./hermes/configure_local_primary.sh

# 4) GitHub — use a PAT, not your GitHub account password
./scripts/auth_github.sh
# or:  echo 'GITHUB_TOKEN=ghp_...' >> .env && ./scripts/auth_github.sh
# or:  gh auth login -h github.com -p https -w

# 5) Workspaces (optional)
# edit .env: WORKSPACE_REPOS="https://github.com/you/app.git"
./scripts/clone_workspaces.sh

./scripts/doctor.sh
```

If doctor says **model coder-64k missing** after a successful create, you almost always created the model *before* `OLLAMA_MODELS` pointed at the SSD — run steps 2 again.

Non-root installs no longer need write access to `/opt`. Empty `WORKSPACE_ROOT` in `.env.example` falls back to `~/workspaces` or `$AUTOCODE_DATA_ROOT/workspaces`.

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
- `coder-64k` Modelfile — name kept; default `num_ctx` is **16384 on Jetson** (set `OLLAMA_NUM_CTX=65536` only if VRAM allows)
- `OLLAMA_KEEP_ALIVE=24h`
- Smoke `/api/chat` (tiny `num_ctx` first)
- Boot auto-start: `./scripts/install_hawkeye_autostart.sh` (UI + Ollama; tunnel when configured)

**Gotcha:** Orin Nano **8GB** cannot load `qwen2.5-coder:7b` (`cudaMalloc failed: out of memory`). Default base is **`qwen2.5-coder:3b`**. AGX/32GB+ can set `BASE_MODEL=qwen2.5-coder:7b`.

**Gotcha:** Listing models is not enough — chat needs `/usr/local/lib/ollama/llama-server`. If smoke returns `llama-server binary not found`, re-run `./ollama/install_ollama_jetson.sh` (or the Jetson AI Lab container).

**Gotcha:** GitHub rejects account passwords for `git`/`gh` — use a PAT (`./scripts/auth_github.sh`).

## Phase 2 — Hermes

- Primary = local `coder-64k`
- Smoke: `scripts/smoke_hermes.sh`
- Fallbacks only after local works

## Phase 3 — autopilot

- Notion provision (`notion/client.py provision --seed`) or `go_live.sh`
- Supervised night: `./cron/overnight_run.sh --force`
- `AUTOCODE_AUTOPILOT_ENABLED=1` + `cron/install_autopilot_timers.sh`
