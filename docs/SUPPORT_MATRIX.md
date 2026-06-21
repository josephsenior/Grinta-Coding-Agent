# Support Matrix

This matrix defines what Grinta currently supports for official OSS releases.

## Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| Linux | Supported | Required CI gate runs full `backend/tests` with coverage (`gates-on-linux`). |
| Windows | Supported | Required CI gate runs `backend/tests/unit` (`gates-on-windows`). |
| macOS | Supported | Required CI gate runs `backend/tests/unit` (`gates-on-macos`). |

### macOS platform policy

macOS is a **required release platform** alongside Linux and Windows. The
`gates-on-macos` job in [`.github/workflows/py-tests.yml`](../.github/workflows/py-tests.yml)
runs the full unit corpus on every PR and on `main`.

Contributors on Mac should still run `pytest backend/tests/unit` locally before
opening PRs that touch shell, terminal, or path handling.

## Platform parity gaps

Grinta is **cross-platform by design**, not OS-transparent. The execution layer
routes through `OS_CAPS` and `UnifiedShellSession`, but some capabilities differ
by host OS. Treat this table as the honest parity contract.

| Area | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Core agent loop (read/edit/run/git) | Full | Full | Full (best effort) |
| Interactive terminal (tmux-backed) | Full | Not available natively | Full |
| Interactive terminal (PTY / subprocess fallback) | Available | Limited interactivity | Available |
| Workspace setup scripts | `.grinta/setup.sh` | `.grinta/setup.ps1` preferred; `.grinta/setup.sh` via Git Bash | `.grinta/setup.sh` |
| Git pre-commit hooks | `.grinta/pre-commit.sh` | `.grinta/pre-commit.ps1` preferred; `.grinta/pre-commit.sh` via Git Bash | `.grinta/pre-commit.sh` |
| `sandboxed_local` profile | bubblewrap (`bwrap`) | AppContainer | `sandbox-exec` |
| MCP (local runtime / action client) | Full | Full (HTTP/SSE + allowlisted stdio) | Full |
| MCP (remote action-execution client) | Full | Full when server exposes MCP | Full |
| Default cache directory | System temp (`<temp>/grinta/cache`) | Same | Same |
| CI certification depth | Full tests + coverage + integration | Unit tests | Unit tests (required) |

When a feature is **limited** rather than **absent**, the runtime logs a warning
and the agent prompt layer (`terminal_contract`) steers the model toward the
active shell contract (PowerShell vs bash).

## Python

| Version | Status |
| --- | --- |
| 3.12 | Supported |
| 3.13 | Supported |

## Installation Paths

| Method | Status | Notes |
| --- | --- | --- |
| `pipx install grinta-ai` | Supported | Preferred for end users. |
| Source (`uv run python -m backend.cli.entry`) | Supported | Preferred for contributors. |
| Docker | Community / experimental | Container images may be available, but this repo does not provide an officially supported `docker compose` stack. |
| Homebrew / Scoop | Supported | Community package managers, validated during release process. |

## Product Surface

Grinta is supported as a **terminal-first coding agent**. Interactive TTY runs use
the Textual TUI; piped stdin uses the non-interactive runner. Legacy server-era
references in historical docs/changelog entries should not be treated as current
supported product surfaces.
