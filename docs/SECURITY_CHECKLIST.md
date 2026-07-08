# Grinta Security Checklist

Grinta is **local-first** and runs with **your** user privileges. It is **not** a sandbox. Read this before pointing it at code you do not fully trust.

## Threat model

- **In scope:** untrusted prompts in trusted code; trusted prompts in trusted code.
- **Out of scope:** untrusted code (e.g., a freshly cloned repo containing malicious build scripts), multi-user isolation, remote attacker scenarios.

## Before each session

- [ ] I trust the repository (no malicious `package.json` scripts, no rogue `Makefile`, no `.envrc` I didn't write)
- [ ] My `settings.json` does **not** contain the only copy of any secret — store real keys in environment variables or a sibling `.env` file and reference them with `${VAR}` in `settings.json` (see `backend/core/config/api_key_manager.py`)
- [ ] I have a clean git working tree (so `git diff` is meaningful as an audit trail)
- [ ] I know my autonomy level (`/autonomy`) — **conservative** for unfamiliar repos, **balanced** (default) for normal work. Grinta prompts on first open of a new workspace.

## Built-in protections

| Protection | What it does |
| --- | --- |
| **Runtime critical-command gate** | Blocks CRITICAL-classified shell and terminal commands while security enforcement is enabled |
| **Hardened-local policy** | When `security.execution_profile` is `hardened_local` or `sandboxed_local`, blocks workspace escapes, package installs, network-capable commands, background processes, and sensitive path access unless explicitly allowed |
| **Autonomy confirmation gate** | `/autonomy conservative|balanced|full` controls when the agent pauses for approval; it is not the security profile |
| **Audit log** | Every action logged to `~/.grinta/workspaces/<id>/storage/<session>/audit/` with risk classification |
| **Secret masker** | Known secret patterns stripped from output before display/logging |
| **Shell guard** | Detects `rm -rf /`, force pushes, encoded payloads, privilege escalation, network exfiltration |
| **File viewer scoping** | Localhost-only file preview server rejects paths outside configured workspace roots |

## Read-outside-workspace (`allow_read_outside_workspace`)

- Default is **off**. When enabled, only paths listed in `additional_read_roots` become readable (not the whole filesystem).
- A sensitive-path deny list always blocks common secret locations (`.ssh`, `.env`, `.npmrc`, `.docker/config.json`, …).
- **Shell bypass:** file-read tools honor the boundary, but Agent-mode shell commands (`cat`, `Get-Content`, …) do not. Use `hardened_local` or conservative autonomy on unfamiliar repos.

## What Grinta is **not**

| Misconception | Reality |
| --- | --- |
| A sandbox | Pattern matching can be bypassed by clever prompt injection or obfuscation |
| Isolated from filesystem | `hardened_local` enforces Grinta policy checks, but actions still run with your host-user permissions |
| Safe against malicious builds | Authorized tools (e.g., `npm install` on untrusted `package.json`) can trigger malicious scripts |

## Hardening recommendations

- [ ] Run untrusted repos in a VM or container (disposable Docker or fresh user account with limited ACLs)
- [ ] Use **conservative** autonomy for unfamiliar repos
- [ ] Review the audit log (`~/.grinta/workspaces/<id>/storage/<session>/audit/`) after long sessions
- [ ] Scope API keys to per-project with low spend limits
- [ ] Pin Grinta to a known version in production-adjacent workflows; track `CHANGELOG.md`
- [ ] Disable network-using commands when working offline (`security.allow_network_commands: false` in `settings.json`)

## Trust boundary: `settings.json` and plugins

Grinta reads `settings.json` and any installed plugin source at startup and trusts them as part of the trusted compute base. Two surfaces in particular execute Python code on import:

* **`agent.classpath`** — when an `agent` block has a `classpath` field, Grinta does `importlib.import_module(<classpath>)` to load the agent class. Any Python module whose dotted path you put in `classpath` will have its top-level code run at config load. Treat `settings.json` like a Python file: only let trusted sources write it.
* **`agentskills` plugin loader** — Grinta's plugin loader (`backend/execution/plugins/agent_skills/`) statically imports skill modules. There is no permission model or sandbox. A skill is a Python function with full process privileges. Do not install skills from untrusted sources.

The same rule applies to the MCP servers you enable under `mcp_config.servers`: each `command` is spawned as a child process. The risk is the server itself, not Grinta's loader, but the trust boundary is identical — only enable MCP servers you have read the source of.

## Reporting a vulnerability

See [`SECURITY.md`](../SECURITY.md). Do **not** open a public issue.
