# Contributing

Thanks for helping make Autocode easier to run on local hardware.

## Ground rules

- **No secrets** in commits, issues, or PR descriptions (tokens, keys, private Notion URLs with auth).
- Prefer small PRs with a clear problem → fix.
- Match existing shell/Python style; keep scripts `set -euo pipefail` where practical.
- Docs changes for setup friction are especially welcome.

## Dev loop

```bash
git clone https://github.com/<you>/Autocode.git
cd Autocode
cp .env.example .env   # leave secrets empty for lint/docs work
./scripts/setup.sh --check
```

On a Jetson (or aarch64 box with GPU), follow the README Quick start for a real install.

## PR checklist

- [ ] `.env` / real tokens not included
- [ ] New user-facing steps reflected in `README.md` or `docs/`
- [ ] Scripts are executable and documented
