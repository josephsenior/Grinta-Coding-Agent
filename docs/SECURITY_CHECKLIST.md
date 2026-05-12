# Grinta Security Checklist

Grinta is **local-first** and runs with **your** user privileges. It is **not** a sandbox. Read this before pointing it at code you do not fully trust.

## Threat model

- **In scope:** untrusted prompts in trusted code; trusted prompts in trusted code.
- **Out of scope:** untrusted code (e.g., a freshly cloned repo containing malicious build scripts), multi-user isolation, remote attacker scenarios.

## Before each session

- [ ] I trust the repository (no malicious `package.json` scripts, no rogue `Makefile`, no `.envrc` I didn't write)
- [ ] My `settings.json` does **not** contain the only copy of any secret — secrets live in OS keychain or `.env` files via `${VAR}` syntax
- [ ] I have a clean git working tree (so `git diff` is meaningful as an audit trail)
- [ ] I know my autonomy level (`/autonomy`) — **conservative** for unfamiliar repos, **balanced** (default) for normal work

## Built-in protections

| Protection | What it does |
| --- | --- |
| **Hardened-local policy** | `command_analyzer.py` classifies commands: NONE / LOW / MEDIUM / HIGH / CRITICAL |
| **CRITICAL refusal gate** | `safety_validator.py::_should_block_action` blocks all CRITICAL actions regardless of profile |
| **Audit log** | Every action logged to `~/.grinta/workspaces/<id>/storage/<session>/audit/` with risk classification |
| **Secret masker** | Known secret patterns stripped from output before display/logging |
| **Shell guard** | Detects `rm -rf /`, force pushes, encoded payloads, privilege escalation, network exfiltration |

## What Grinta is **not**

| Misconception | Reality |
| --- | --- |
| A sandbox | Pattern matching can be bypassed by clever prompt injection or obfuscation |
| Isolated from filesystem | `hardened_local` *prefers* workspace boundaries but does not strictly enforce them |
| Safe against malicious builds | Authorized tools (e.g., `npm install` on untrusted `package.json`) can trigger malicious scripts |

## Hardening recommendations

- [ ] Run untrusted repos in a VM or container (disposable Docker or fresh user account with limited ACLs)
- [ ] Use **conservative** autonomy for unfamiliar repos
- [ ] Review the audit log (`~/.grinta/workspaces/<id>/storage/<session>/audit/`) after long sessions
- [ ] Scope API keys to per-project with low spend limits
- [ ] Pin Grinta to a known version in production-adjacent workflows; track `CHANGELOG.md`
- [ ] Disable network-using tools in `settings.json` `permissions` block when working offline

## Reporting a vulnerability

See [`SECURITY.md`](../SECURITY.md). Do **not** open a public issue.
