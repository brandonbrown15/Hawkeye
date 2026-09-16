#!/usr/bin/env bash
# Open-source friendly setup: local .env only, never commit secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECK_ONLY=0
YES=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) YES=1 ;;
    -h|--help)
      echo "Usage: ./scripts/setup.sh [--check] [--yes]"
      exit 0
      ;;
  esac
done

ok() { echo "  OK  $*"; }
fail() { echo "  FAIL $*"; }

echo "== Autocode setup =="

check_git() {
  local bad=0
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if git ls-files --error-unmatch .env >/dev/null 2>&1; then
      fail ".env is tracked by git"
      bad=1
    else
      ok ".env not tracked"
    fi
    if git ls-files --error-unmatch notion/ids.yaml >/dev/null 2>&1; then
      fail "notion/ids.yaml is tracked"
      bad=1
    else
      ok "notion/ids.yaml not tracked"
    fi
  fi
  return "$bad"
}

check_layout() {
  local required=(
    .env.example
    README.md
    LICENSE
    SECURITY.md
    CONTRIBUTING.md
    bootstrap/00_check_jetson.sh
    bootstrap/01_setup_swap.sh
    bootstrap/02_enable_maxn.sh
    bootstrap/03_install_gh.sh
    bootstrap/04_install_tailscale.sh
    bootstrap/05_use_data_ssd.sh
    ollama/Modelfile.coder-64k
    ollama/install_ollama_jetson.sh
    ollama/create_coder_64k.sh
    hermes/config.stub.yaml
    hermes/install_hermes.sh
    hermes/configure_local_primary.sh
    notion/client.py
    notion/ids.example.yaml
    orchestrator/run_night.py
    cron/overnight_run.sh
    cron/install_autopilot_timers.sh
    docs/notion-setup.md
    docs/security.md
    docs/guardrails.md
    docs/supervised-first-run.md
    docs/routing.md
    docs/go-live.md
    docs/hermes-overnight-skill.md
    START_HERE.md
    start
    scripts/demo_night.sh
    scripts/bootstrap_jetson.sh
    scripts/go_live.sh
    scripts/auth_github.sh
    scripts/connect_notion.sh
    scripts/connect_notion.py
    scripts/doctor.sh
    scripts/smoke_hermes.sh
    scripts/delegate_cursor.sh
    scripts/delegate_grok.sh
    docs/how-ai-talks.md
    docs/ui.md
    docs/continuous.md
    docs/remote-ops.md
    ui/server.py
    ui/static/index.html
    ui/static/app.css
    ui/static/app.js
    scripts/ui.sh
    cron/worker_run.sh
    cron/autocode-worker.timer
    cron/autocode-worker.service
    cron/autocode-ui.service
    cron/install_autopilot_timers.sh
  )
  local missing=0
  for f in "${required[@]}"; do
    if [[ -e "$f" ]]; then ok "$f"; else fail "missing $f"; missing=1; fi
  done
  return "$missing"
}

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  rc=0
  check_layout || rc=1
  check_git || rc=1
  echo "Check complete."
  exit "$rc"
fi

check_layout || true
check_git || true

[[ -f .env ]] || { cp .env.example .env; ok "Created .env"; }
[[ -f notion/ids.yaml ]] || { cp notion/ids.example.yaml notion/ids.yaml; ok "Created notion/ids.yaml (gitignored)"; }
mkdir -p logs state
chmod +x bootstrap/*.sh ollama/*.sh hermes/*.sh cron/*.sh scripts/*.sh notion/client.py 2>/dev/null || true
ok "logs/ state/ + executable bits"

if [[ "$YES" -eq 0 && -t 0 ]]; then
  echo
  echo "Optional prompts (Enter skips). Values stay in local .env only."
  read -r -p "NOTION_TOKEN: " notion_token || true
  read -r -p "NOTION_BUILD_QUEUE_DB: " bq || true
  read -r -p "NOTION_AGENT_RUNS_DB: " ar || true
  read -r -p "NOTION_ESCALATION_LOG_DB: " el || true
  read -r -p "TELEGRAM_BOT_TOKEN: " tg || true
  read -r -p "TELEGRAM_CHAT_ID: " chat || true
  read -r -p "WORKSPACE_REPOS: " repos || true

  set_env() {
    local key="$1" val="$2"
    [[ -z "$val" ]] && return 0
    if grep -q "^${key}=" .env; then
      awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{$2=v} {print}' .env >.env.tmp && mv .env.tmp .env
    else
      echo "${key}=${val}" >>.env
    fi
  }
  set_env NOTION_TOKEN "${notion_token:-}"
  set_env NOTION_BUILD_QUEUE_DB "${bq:-}"
  set_env NOTION_AGENT_RUNS_DB "${ar:-}"
  set_env NOTION_ESCALATION_LOG_DB "${el:-}"
  set_env TELEGRAM_BOT_TOKEN "${tg:-}"
  set_env TELEGRAM_CHAT_ID "${chat:-}"
  set_env WORKSPACE_REPOS "${repos:-}"
fi

cat <<'EOF'

Next (easiest):
  ./start

Or fully auto without prompts (after .env is filled):
  ./scripts/go_live.sh --local-only --first-night --enable-autopilot

Never commit .env. Re-run: ./scripts/setup.sh --check
EOF
