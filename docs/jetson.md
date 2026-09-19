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
./ollama/prepare_jetson_memory.sh
./ollama/ensure_ollama.sh --restart
./ollama/create_coder_64k.sh
# Orin Nano: defaults to qwen2.5-coder:3b + 4k ctx.
# Still OOM? try 1.5b or CPU-only:
#   BASE_MODEL=qwen2.5-coder:1.5b OLLAMA_NUM_CTX=4096 ./ollama/create_coder_64k.sh
#   OLLAMA_NUM_GPU=0 BASE_MODEL=qwen2.5-coder:3b OLLAMA_NUM_CTX=4096 ./ollama/create_coder_64k.sh
# Prove: ollama run coder-64k OK
# Free disk: ollama rm qwen2.5-coder:7b qwen2.5-coder:1.5b

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

## UI access, autostart, public URL, API tokens

### Why `https://hawkeye.brownhawke.engineering` is blank
The UI binds **`127.0.0.1:8787` only**. That hostname works only after a **Cloudflare Tunnel** on this Jetson points at that port. Until then the public site has nothing behind it.

### Open the UI today
```bash
# On the Jetson itself (or via SSH tunnel from your laptop):
./scripts/ui.sh
# → http://127.0.0.1:8787/

# From your laptop:
ssh -L 8787:127.0.0.1:8787 shaggy@<jetson-ip>
# then open http://127.0.0.1:8787/ on the laptop

# Or Tailscale:
sudo tailscale up
./scripts/ui.sh --remote
# → http://<tailscale-ip>:8787/
```

Login: work email `@brownhawke.engineering` + password hash in `config/users.json`.  
Reset without putting the secret in git / shell history:

```bash
./scripts/hawkeye accounts set-password --email mark@brownhawke.engineering
```

Full login path + Mark runbook: [login.md](login.md).

### Autostart on boot
```bash
./scripts/install_hawkeye_autostart.sh
sudo loginctl enable-linger "$USER"
systemctl --user status hawkeye-ui.service
systemctl --user is-enabled hawkeye-ui.service
```
Also keep Ollama on boot: `sudo systemctl enable --now ollama`.

### Public hostname (Cloudflare Tunnel)
On a laptop/browser (Cloudflare dashboard):
1. Zero Trust → Networks → Tunnels → **Create** → name `hawkeye`
2. Copy the **token** (or install command)
3. On the Jetson:
```bash
# install cloudflared (arm64)
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /tmp/cloudflared
sudo install -m 755 /tmp/cloudflared /usr/local/bin/cloudflared

# put token in .env
echo 'TUNNEL_TOKEN=eyJ…' >> ~/Hawkeye/.env

# Public hostname in dashboard: hawkeye.brownhawke.engineering → http://127.0.0.1:8787

./scripts/install_hawkeye_autostart.sh   # enables hawkeye-tunnel.service
systemctl --user status hawkeye-tunnel.service
```

### Link API tokens in the UI (Account → Connections + Machine)
After pulling this branch (or merged main):
1. Open Hawkeye in the browser (public URL or SSH/Tailscale `:8787`) → sign in
2. **Account → Machine** — paste Cloudflare Tunnel install token, set `HAWKEYE_MEMORY_KEY`, choose auto-update branch, enable 5‑minute GitHub pulls
3. **Account → Connections** — save Notion / GitHub / Cursor / Claude / ChatGPT / Grok / Brave / Telegram per user  

Secrets encrypt with the memory key and are used at runtime for your session. Machine `.env` remains a fallback for overnight autopilot.

See [accounts.md](accounts.md).

### Keep the Jetson up to date (auto-update)
`./scripts/install_hawkeye_autostart.sh` enables `hawkeye-update.timer` (every 5 minutes):
- `git fetch` + fast-forward pull of `HAWKEYE_UPDATE_BRANCH` (default: **main**)
- Recreate `coder-64k` when Modelfile changes
- Restart `hawkeye-ui` so laptop UI changes land on the Orin without SSH

```bash
./scripts/hawkeye_self_update.sh --check
# pause: Account → Machine → uncheck auto-update, or HAWKEYE_UPDATE_ENABLED=0
```

`--force` restarts the UI but **will not pull** while the working tree is dirty (`working-tree=dirty`). That is why a live box can sit on an old SHA after `main` moved.

### Stuck dirty checkout (no Tailscale) — recover to `main`

If Account → Machine → Force update refuses (`working-tree=dirty`) and the new Discard button is not on this SHA yet, run this **on the Jetson** (local console / HDMI / existing SSH — not Tailscale):

```bash
# Typical clone; adjust if Hawkeye lives elsewhere
cd ~/Hawkeye

git fetch origin main
git status --porcelain
# Expect dirty tracked files. .env is gitignored and is NOT discarded.

# Discard tracked local edits and land on origin/main (e.g. 72d6230 + Wake Ollama)
git checkout -B main origin/main
# If checkout is blocked by untracked files (keeps gitignored .env):
#   git clean -fd
#   git checkout -B main origin/main

./scripts/hawkeye_self_update.sh --reset   # same reset + UI restart (once this SHA is present)
systemctl --user restart hawkeye-ui.service
./ollama/ensure_ollama.sh
sudo systemctl enable --now ollama 2>/dev/null || true

git rev-parse --short HEAD   # should match origin/main
```

After this lands, Account → Machine → **Discard local changes and update** is the admin UI equivalent (`hawkeye_self_update.sh --reset`). `.env` stays; only tracked dirty files are thrown away.

Then: Account → Machine → **Wake Ollama**, Local only OFF, and chat escalate can use the Cursor API key saved under Connections.

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

**Gotcha:** Orin Nano **8GB** often cannot load `7b` (`cudaMalloc failed`). Default is **`qwen2.5-coder:3b` @ 4k ctx**. If that OOMs under load, fall back to `1.5b` or `OLLAMA_NUM_GPU=0` (CPU). Run `./ollama/prepare_jetson_memory.sh` before chat smoke.

**Gotcha:** Listing models is not enough — chat needs `/usr/local/lib/ollama/llama-server`. If smoke returns `llama-server binary not found`, re-run `./ollama/install_ollama_jetson.sh`.

**Gotcha:** GitHub rejects account passwords for `git`/`gh` — use a PAT (`./scripts/auth_github.sh`). Transient `Could not resolve host: github.com` is DNS/network — retry `git pull` later.

## Phase 2 — Hermes

- Primary = local `coder-64k`
- Smoke: `scripts/smoke_hermes.sh`
- Fallbacks only after local works

## Phase 3 — autopilot

- Notion provision (`notion/client.py provision --seed`) or `go_live.sh`
- Supervised night: `./cron/overnight_run.sh --force`
- `AUTOCODE_AUTOPILOT_ENABLED=1` + `cron/install_autopilot_timers.sh`
