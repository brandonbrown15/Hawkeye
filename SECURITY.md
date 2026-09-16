# Security policy

## Supported versions

This project is early / pre-1.0. Report issues against `main`.

## Reporting a vulnerability

Please **do not** open a public issue for credential leaks or exploitable flaws.

Email the maintainer via the GitHub profile on this repository, or use GitHub **Private vulnerability reporting** if enabled.

Include:

- Affected commit / release
- Impact (e.g. token exposure, remote Ollama access)
- Reproduction steps

## Secret handling

See [docs/security.md](docs/security.md). Never commit `.env` or live API tokens.
