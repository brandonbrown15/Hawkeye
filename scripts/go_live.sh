#!/usr/bin/env bash
# Fully automatic Jetson go-live for Autocode.
# Chains bootstrap → GitHub auth → Notion provision/seed → mock night → optional live night + timer.
#
# Supply secrets once in .env (or the environment):
#   NOTION_TOKEN + NOTION_HUB_PAGE   (hub page shared with the integration)
#   GITHUB_TOKEN                     (or run gh auth login once)
#   WORKSPACE_REPOS                  (repos to clone)
#   CURSOR_WEBHOOK_URL / GROK_BOT_WEBHOOK_URL  (optional until you want cloud escalate)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENABLE_AUTOPILOT=0
FIRST_NIGHT=0
SKIP_BOOTSTRAP=0
SEED=1
LOCAL_ONLY=0

usage() {
  cat <<'EOF'
Usage: scripts/go_live.sh [options]

One-command path from a fresh Jetson clone to overnight autopilot.

Options:
  --enable-autopilot  If doctor has no FAILs, set AUTOCODE_AUTOPILOT_ENABLED=1
                      and install the systemd timer
  --first-night       After mock demo, run one live night with --force
  --skip-bootstrap    Skip host/Ollama/Hermes bootstrap (re-run config only)
  --no-seed           Do not seed a Ready Local-safe Notion task
  --local-only        Soften cloud-delegate warnings; local Hermes is enough to enable
  -h, --help          Show help

Minimal .env before running:
  NOTION_TOKEN=secret_...
  NOTION_HUB_PAGE=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  GITHUB_TOKEN=ghp_...                 # or authenticate gh beforehand
  WORKSPACE_REPOS=owner/repo           # optional but recommended
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-autopilot) ENABLE_AUTOPILOT=1; shift ;;
    --first-night) FIRST_NIGHT=1; shift ;;
    --skip-bootstrap) SKIP_BOOTSTRAP=1; shift ;;
    --no-seed) SEED=0; shift ;;
    --local-only) LOCAL_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

step() {
  echo
  echo "============================================================"
  echo "▶ $1"
  echo "============================================================"
}

upsert_env() {
  local key="$1" val="$2"
  KEY="$key" VAL="$val" python3 - <<'PY'
import os
from pathlib import Path
key, val = os.environ["KEY"], os.environ["VAL"]
env_path = Path(".env")
lines = env_path.read_text().splitlines() if env_path.exists() else []
out, found = [], False
for line in lines:
    if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
        out.append(f"{key}={val}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={val}")
env_path.write_text("\n".join(out) + "\n")
print(f"Set {key}={val}")
PY
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
# shellcheck disable=SC1091
set -a
source .env
set +a

if [[ "${LOCAL_ONLY}" -eq 1 ]]; then
  upsert_env AUTOCODE_LOCAL_ONLY 1
  export AUTOCODE_LOCAL_ONLY=1
fi

if [[ "${SKIP_BOOTSTRAP}" -eq 0 ]]; then
  step "1/8 Bootstrap Jetson stack"
  bash "${ROOT}/scripts/bootstrap_jetson.sh" -y || {
    echo "WARN: bootstrap reported issues — continuing; doctor will catch hard FAILs."
  }
else
  step "1/8 Bootstrap skipped"
fi

step "2/8 GitHub auth"
if bash "${ROOT}/scripts/auth_github.sh"; then
  echo "GitHub auth OK"
else
  echo "WARN: GitHub auth incomplete — PRs will fail until gh auth login / GITHUB_TOKEN"
fi

step "3/8 Clone workspaces"
bash "${ROOT}/scripts/clone_workspaces.sh" || {
  echo "WARN: workspace clone incomplete"
}

step "4/8 Notion provision"
if [[ -z "${NOTION_TOKEN:-}" ]]; then
  echo "WARN: NOTION_TOKEN unset — skipping provision (mock nights still work)"
elif [[ -z "${NOTION_HUB_PAGE:-}" && -z "${NOTION_BUILD_QUEUE_DB:-}" ]]; then
  echo "WARN: Set NOTION_HUB_PAGE (empty page shared with integration) to auto-create DBs"
  echo "      Or set NOTION_BUILD_QUEUE_DB / NOTION_AGENT_RUNS_DB / NOTION_ESCALATION_LOG_DB manually"
else
  if [[ -n "${NOTION_HUB_PAGE:-}" ]]; then
    PROV_ARGS=(--parent "${NOTION_HUB_PAGE}")
    if [[ "${SEED}" -eq 1 ]]; then
      PROV_ARGS+=(--seed)
      if [[ -n "${WORKSPACE_REPOS:-}" ]]; then
        first_repo="$(echo "${WORKSPACE_REPOS}" | awk '{print $1}')"
        PROV_ARGS+=(--seed-repo "${first_repo}")
      fi
    fi
    python3 "${ROOT}/notion/client.py" provision "${PROV_ARGS[@]}"
  elif [[ "${SEED}" -eq 1 ]]; then
    SEED_ARGS=()
    if [[ -n "${WORKSPACE_REPOS:-}" ]]; then
      SEED_ARGS+=(--repo "$(echo "${WORKSPACE_REPOS}" | awk '{print $1}')")
    fi
    python3 "${ROOT}/notion/client.py" seed "${SEED_ARGS[@]}"
  fi
  # reload env after provision wrote DB ids
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

step "5/8 Mock night"
bash "${ROOT}/scripts/demo_night.sh" || {
  echo "FAIL: mock night failed"
  exit 1
}

step "6/8 Doctor"
DOCTOR_RC=0
bash "${ROOT}/scripts/doctor.sh" || DOCTOR_RC=$?
if [[ "${DOCTOR_RC}" -ne 0 ]]; then
  echo "Doctor reported FAILs (exit ${DOCTOR_RC})."
  if [[ "${ENABLE_AUTOPILOT}" -eq 1 || "${FIRST_NIGHT}" -eq 1 ]]; then
    echo "Refusing --enable-autopilot / --first-night until doctor is green."
    exit 1
  fi
fi

if [[ "${FIRST_NIGHT}" -eq 1 ]]; then
  step "7/8 First live night (--force)"
  bash "${ROOT}/cron/overnight_run.sh" --force
else
  step "7/8 First live night skipped (pass --first-night to run)"
fi

if [[ "${ENABLE_AUTOPILOT}" -eq 1 ]]; then
  step "8/8 Enable autopilot timer"
  upsert_env AUTOCODE_AUTOPILOT_ENABLED 1
  bash "${ROOT}/cron/install_autopilot_timers.sh"
  echo "Autopilot enabled. Timer will call overnight_run.sh."
else
  step "8/8 Autopilot left disabled"
  echo "When ready: set AUTOCODE_AUTOPILOT_ENABLED=1 and run cron/install_autopilot_timers.sh"
  echo "Or re-run: ./scripts/go_live.sh --skip-bootstrap --enable-autopilot"
fi

cat <<'EOF'

============================================================
go_live finished
============================================================
Remote ops:  ./scripts/status.sh
             ./scripts/control.sh pause|resume|abort|skip <id>
Docs:        docs/go-live.md
EOF
