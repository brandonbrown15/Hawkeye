#!/usr/bin/env bash
# Pull latest Hawkeye from GitHub and refresh local UI + Ollama when needed.
#
# Usage:
#   ./scripts/hawkeye_self_update.sh           # no-op if already up to date
#   ./scripts/hawkeye_self_update.sh --force   # restart UI even if no git change
#   ./scripts/hawkeye_self_update.sh --check   # print status only
#   ./scripts/hawkeye_self_update.sh --reset   # discard tracked local changes; align to remote branch
#
# Env:
#   HAWKEYE_UPDATE_ENABLED=0     skip updates (timer still fires, exits 0)
#   HAWKEYE_UPDATE_BRANCH=main   remote branch to track (default: main)
#   HAWKEYE_UPDATE_REMOTE=origin
#   HAWKEYE_UPDATE_RECREATE_MODEL=1  rebuild coder-64k when Modelfile changes
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a || true

FORCE=0
CHECK_ONLY=0
RESET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    --reset|--discard-local) RESET=1; FORCE=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

ENABLED="${HAWKEYE_UPDATE_ENABLED:-1}"
BRANCH="${HAWKEYE_UPDATE_BRANCH:-main}"
if [[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]]; then
  BRANCH="main"
fi
REMOTE="${HAWKEYE_UPDATE_REMOTE:-origin}"
RECREATE_MODEL="${HAWKEYE_UPDATE_RECREATE_MODEL:-1}"
LOG_DIR="${ROOT}/logs"
STATE_DIR="${ROOT}/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"
LOG="$LOG_DIR/self-update.log"
LOCK="$STATE_DIR/self-update.lock"
MODELFILE_HASH="$STATE_DIR/coder-64k.modelfile.sha256"
MODEL_PIN_HASH="$STATE_DIR/coder-64k.base-pin.sha256"

log() {
  local line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  echo "$line" | tee -a "$LOG"
}

sysctl_user() {
  if systemctl --user status hawkeye-ui.service >/dev/null 2>&1 \
    || systemctl --user list-unit-files hawkeye-ui.service 2>/dev/null | grep -q hawkeye-ui; then
    systemctl --user "$@"
    return $?
  fi
  return 1
}

if [[ "$ENABLED" != "1" && "$FORCE" -eq 0 && "$CHECK_ONLY" -eq 0 ]]; then
  log "HAWKEYE_UPDATE_ENABLED=${ENABLED} — skipping"
  exit 0
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  log "Another self-update is running — skip"
  exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "ERROR: $ROOT is not a git checkout"
  exit 1
fi

DIRTY=0
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  DIRTY=1
fi

BEFORE="$(git rev-parse HEAD)"
log "Fetch ${REMOTE}/${BRANCH} (at ${BEFORE:0:8})"
if ! git fetch --quiet "$REMOTE" "$BRANCH"; then
  log "ERROR: git fetch failed (check SSH key / gh auth / network)"
  exit 1
fi

REMOTE_REV="$(git rev-parse "${REMOTE}/${BRANCH}")"
if [[ "$CHECK_ONLY" -eq 1 ]]; then
  if [[ "$BEFORE" == "$REMOTE_REV" ]]; then
    echo "up-to-date ${BEFORE:0:8} (${REMOTE}/${BRANCH})"
  else
    echo "behind local=${BEFORE:0:8} remote=${REMOTE_REV:0:8}"
  fi
  if [[ "$DIRTY" -eq 1 ]]; then
    echo "working-tree=dirty"
    echo "hint: Account → Machine → Discard local changes, or: $0 --reset"
  fi
  exit 0
fi

UPDATED=0
if [[ "$RESET" -eq 1 ]]; then
  log "RESET: discarding tracked local changes; align to ${REMOTE}/${BRANCH}"
  while IFS= read -r line; do
    [[ -n "$line" ]] && log "  dirty: $line"
  done < <(git status --porcelain 2>/dev/null || true)
  # Never git clean -x — .env and other gitignored secrets must stay.
  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "$BRANCH" ]]; then
    if ! git checkout -f -B "$BRANCH" "${REMOTE}/${BRANCH}"; then
      log "WARN: checkout blocked by untracked files; git clean -fd (keeps gitignored .env)"
      git clean -fd
      git checkout -f -B "$BRANCH" "${REMOTE}/${BRANCH}"
    fi
  else
    git reset --hard "${REMOTE}/${BRANCH}"
  fi
  AFTER="$(git rev-parse HEAD)"
  log "Reset ${BEFORE:0:8} → ${AFTER:0:8} (${REMOTE}/${BRANCH})"
  UPDATED=1
elif [[ "$DIRTY" -eq 1 ]]; then
  log "WARN: working tree dirty — refusing auto-pull (commit/stash local edits first)"
  if [[ "$FORCE" -eq 0 ]]; then
    exit 0
  fi
  log "WARN: --force with dirty tree; will restart services only (no pull)"
  if [[ "$BEFORE" != "$REMOTE_REV" ]]; then
    log "ERROR: cannot pull while dirty (use --reset to discard tracked local changes)"
    exit 1
  fi
  AFTER="$BEFORE"
elif [[ "$BEFORE" != "$REMOTE_REV" ]]; then
  # Stay on the tracking branch if already on it. Do NOT auto-checkout another
  # branch (that yanked Jetson hotfixes back to main every 5 minutes).
  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" == "$BRANCH" ]]; then
    git pull --ff-only "$REMOTE" "$BRANCH"
    AFTER="$(git rev-parse HEAD)"
    log "Updated ${BEFORE:0:8} → ${AFTER:0:8}"
    UPDATED=1
  elif [[ "${HAWKEYE_UPDATE_FORCE_CHECKOUT:-0}" == "1" ]]; then
    log "On branch ${current}; FORCE_CHECKOUT → ${REMOTE}/${BRANCH}"
    git checkout "$BRANCH"
    git pull --ff-only "$REMOTE" "$BRANCH"
    AFTER="$(git rev-parse HEAD)"
    log "Updated ${BEFORE:0:8} → ${AFTER:0:8}"
    UPDATED=1
  else
    log "WARN: on branch ${current}, tracking ${REMOTE}/${BRANCH} — skip pull (set HAWKEYE_UPDATE_FORCE_CHECKOUT=1 or HAWKEYE_UPDATE_BRANCH=${current} to update)"
    AFTER="$BEFORE"
  fi
else
  log "Already up to date (${BEFORE:0:8})"
  AFTER="$BEFORE"
fi

# Keep Ollama alive / warm for local LLM chat.
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
    sudo systemctl start ollama 2>/dev/null || true
  fi
fi
if command -v ollama >/dev/null 2>&1; then
  # Touch tags so the daemon is awake; ignore failures if still starting.
  curl -fsS "http://${OLLAMA_HOST:-127.0.0.1:11434}/api/tags" >/dev/null 2>&1 || true
fi

# Rebuild coder-64k when Modelfile or BASE_MODEL / ctx pin changed.
MODELFILE="$ROOT/ollama/Modelfile.coder-64k"
if [[ "$RECREATE_MODEL" == "1" && -f "$MODELFILE" ]] && command -v ollama >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  [[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a
  pin_base="$(bash "$ROOT/ollama/default_base_model.sh")"
  pin_ctx="$(bash "$ROOT/ollama/default_num_ctx.sh")"
  new_hash="$(sha256sum "$MODELFILE" | awk '{print $1}')"
  new_pin="$(printf '%s\n%s\n' "$pin_base" "$pin_ctx" | sha256sum | awk '{print $1}')"
  old_hash=""
  old_pin=""
  [[ -f "$MODELFILE_HASH" ]] && old_hash="$(cat "$MODELFILE_HASH" 2>/dev/null || true)"
  [[ -f "$MODEL_PIN_HASH" ]] && old_pin="$(cat "$MODEL_PIN_HASH" 2>/dev/null || true)"
  need_model=0
  if [[ "$UPDATED" -eq 1 && "$new_hash" != "$old_hash" ]]; then
    need_model=1
    log "Modelfile changed — recreating coder-64k ($pin_base @ ${pin_ctx})"
  elif [[ "$new_pin" != "$old_pin" ]]; then
    need_model=1
    log "BASE_MODEL/ctx pin changed ($old_pin → $new_pin) — recreating coder-64k ($pin_base @ ${pin_ctx})"
  elif [[ "$FORCE" -eq 1 && ! -f "$MODELFILE_HASH" ]]; then
    need_model=1
    log "Force recreate coder-64k ($pin_base @ ${pin_ctx})"
  fi
  if [[ "$need_model" -eq 1 ]]; then
    if bash "$ROOT/ollama/create_coder_64k.sh"; then
      echo "$new_hash" >"$MODELFILE_HASH"
      echo "$new_pin" >"$MODEL_PIN_HASH"
      log "coder-64k ready ($pin_base)"
    else
      log "WARN: create_coder_64k.sh failed — UI will still restart"
    fi
  elif [[ -z "$old_hash" || -z "$old_pin" ]]; then
    # First successful track without forcing a rebuild if model already exists.
    echo "$new_hash" >"$MODELFILE_HASH"
    echo "$new_pin" >"$MODEL_PIN_HASH"
  fi
fi

# Refresh systemd unit files from the checkout when we pulled new ones.
if [[ "$UPDATED" -eq 1 || "$FORCE" -eq 1 ]]; then
  UNIT_DIR="${HOME}/.config/systemd/user"
  if [[ -d "$UNIT_DIR" ]]; then
    rewrite_one() {
      local src="$1" dest="$2"
      [[ -f "$src" ]] || return 0
      sed "s|/opt/autocode|${ROOT}|g" "$src" >"$dest"
    }
    rewrite_one "$ROOT/cron/hawkeye-ui.service" "$UNIT_DIR/hawkeye-ui.service"
    rewrite_one "$ROOT/cron/hawkeye-tunnel.service" "$UNIT_DIR/hawkeye-tunnel.service"
    rewrite_one "$ROOT/cron/hawkeye-update.service" "$UNIT_DIR/hawkeye-update.service"
    if [[ -f "$ROOT/cron/hawkeye-update.timer" ]]; then
      cp "$ROOT/cron/hawkeye-update.timer" "$UNIT_DIR/hawkeye-update.timer"
    fi
    systemctl --user daemon-reload 2>/dev/null || true
    log "Refreshed systemd user units under ${UNIT_DIR}"
  fi
fi

if [[ "$UPDATED" -eq 1 || "$FORCE" -eq 1 ]]; then
  if sysctl_user restart hawkeye-ui.service; then
    log "Restarted hawkeye-ui.service"
  else
    log "WARN: could not restart hawkeye-ui.service (is autostart installed?)"
    log "       Run: ./scripts/install_hawkeye_autostart.sh"
  fi
  # Tunnel usually does not need a restart on app-only updates.
fi

log "Done (updated=${UPDATED})"
exit 0
