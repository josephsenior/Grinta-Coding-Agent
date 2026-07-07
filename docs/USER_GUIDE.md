# User Guide

Install: [QUICK_START.md](QUICK_START.md). Config keys: [SETTINGS.md](SETTINGS.md).

## Run

- Installed: `grinta`
- Source: `uv run python -m backend.cli.entry`
- Interactive TTY → Textual UI. Piped stdin → non-interactive (one line = one turn; use TUI for multi-turn).

## Modes (`/mode`)

| Mode | Does |
| --- | --- |
| **Chat** | Read-only Q&A |
| **Plan** | Read-only investigation |
| **Agent** | Full edit + shell loop (default) |

## Autonomy (`/autonomy`)

Only matters in **Agent** mode. Controls confirmation prompts, not execution policy.

| Level | Behavior |
| --- | --- |
| conservative | Confirm shell, edits, terminal, browser, MCP, and delegation |
| balanced | Confirm high-risk (default) |
| full | No prompts; CRITICAL blocks still apply |

Execution hardening: `security.execution_profile` in [SETTINGS.md](SETTINGS.md).

## Slash commands

| Command | Purpose |
| --- | --- |
| `/help` | Commands list |
| `/settings` | Model, API key, MCP |
| `/sessions` `/resume` | Past sessions |
| `/model` `/mode` `/autonomy` | HUD controls |
| `/health` | Fast env check (LLM, git, execution profile); run `grinta doctor` outside TUI for full schema checks |
| `/diff` `/checkpoint` `/compact` | Workspace tools |

## Safety

Runs on your machine. See [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) for untrusted code.
