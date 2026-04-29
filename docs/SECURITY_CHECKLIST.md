# Grinta Security Checklist

Grinta is **local-first** and runs with **your** user privileges. It is **not** a sandbox. Read this before pointing it at code you do not fully trust.

## Threat model

- **In scope:** untrusted prompts in trusted code; trusted prompts in trusted code.
- **Out of scope:** untrusted code (e.g., a freshly cloned repo containing malicious build scripts), multi-user isolation, remote attacker scenarios.

## Before each session

- [ ] You trust the repository you are pointing Grinta at (no malicious `package.json` lifecycle scripts, no rogue `Makefile`, no `.envrc` you didn't write).
- [ ] Your `settings.json` does **not** contain the only copy of any secret — secrets should live in your OS keychain or `.env` files referenced via `${VAR}` syntax.
- [ ] You have a clean git working tree (so `git diff` is meaningful as an audit trail at the end).
- [ ] You know your autonomy level (`/autonomy`). Use `supervised` for unfamiliar repos; `balanced` (default) for normal work.

## Built-in protections

- **Hardened-local execution policy** — `command_analyzer.py` classifies every command into NONE / LOW / MEDIUM / HIGH / CRITICAL.
- **Hard CRITICAL refusal gate** — in `safety_validator.py::_should_block_action`, every CRITICAL-classified action is blocked regardless of profile or model output.
- **Audit log** — every action is appended to `~/.grinta/workspaces/<id>/storage/<session>/audit/` with risk classification and outcome.
- **Secret masker** — known secret patterns are stripped from event-stream output before display/logging.
- **Pattern-based shell guard** — `rm -rf /`, force pushes to protected branches, encoded payloads, privilege escalation, and network exfiltration patterns are detected.

## What Grinta is **not**

- **Not** a sandbox. Pattern matching can be bypassed by sufficiently clever prompt injection or obfuscation.
- **Not** isolated from your filesystem outside the workspace — `hardened_local` *prefers* but does not strictly enforce workspace boundaries.
- **Not** safe against malicious build scripts triggered by tools you authorize (e.g., `npm install` on an untrusted `package.json`).

## Hardening recommendations

1. **Run untrusted repos inside a VM or container.** Use a disposable Docker container or a fresh user account with limited home-directory ACLs.
2. **Stay on `supervised` autonomy** the first time you point Grinta at a new repo.
3. **Review the audit log** (`~/.grinta/workspaces/<id>/storage/<session>/audit/`) at the end of each long session.
4. **Keep your provider API keys scoped.** Use per-project keys with low spend limits where supported.
5. **Pin Grinta to a known version** in production-adjacent workflows; track `CHANGELOG.md`.
6. **Disable network-using tools** in `settings.json` `permissions` block when working offline-only.

## Reporting a vulnerability

See [`SECURITY.md`](../SECURITY.md). Do **not** open a public issue.
