# Guardrails

Non-negotiable operating policy for Autocode on the Jetson.

## Git

- Never push or merge `main` directly.
- Branch: `hermes/<task-id>-short-slug` (e.g. `hermes/bld-7-docs-typo`).
- Prefer tiny PRs over unfinished branches.

## Secrets

- Never invent, rotate, or paste secrets.
- `.env` stays on the Jetson only; `.env.example` is the only committed template.

## Budgets (defaults — tune in `.env`)

| Limit | Default |
|-------|---------|
| Tasks per night | 1–2 |
| Wall time per task | 45–90 min |
| Tool iterations | ~40 |
| Local attempts before escalate | 2 |

## Local-safe (default worker)

- Single-file or small module edits
- Tests / fixtures / docs
- Refactors with clear acceptance
- Scripting / glue
- Bugfixes with a failing test already written

## Must escalate

- New product architecture
- Auth, billing, infra, tunnels, HA
- Multi-repo or unclear requirements
- Repeated test failures / local model thrashing
- Complexity = Cloud-only, or Model route ≠ Local Hermes

## After escalate

1. Write Escalation Log (why + context + branch).
2. Do not burn paid tokens unless policy says auto-escalate.
3. Morning digest surfaces Open escalations for human routing.
