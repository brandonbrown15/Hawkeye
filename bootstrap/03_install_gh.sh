#!/usr/bin/env bash
# Install GitHub CLI (gh) for PR creation from the Jetson.
set -euo pipefail

echo "== Install GitHub CLI (gh) =="

if command -v gh >/dev/null 2>&1; then
  echo "gh already installed: $(gh --version | head -1)"
else
  if command -v apt-get >/dev/null 2>&1; then
    (type -p wget >/dev/null || sudo apt-get install -y wget) >/dev/null
    sudo mkdir -p -m 755 /etc/apt/keyrings
    wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
    sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
    sudo apt-get update -y
    sudo apt-get install -y gh
  else
    echo "FAIL: apt-get not available — install gh manually: https://cli.github.com/"
    exit 1
  fi
fi

echo
if gh auth status >/dev/null 2>&1; then
  echo "OK: gh already authenticated"
  gh auth status
else
  echo "Next (interactive on the Jetson):"
  echo "  gh auth login -h github.com -p https -w"
  echo "Or set GH_TOKEN / GITHUB_TOKEN in .env for non-interactive CI-style auth."
fi
