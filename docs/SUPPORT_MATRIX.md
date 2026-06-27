# Support Matrix

This matrix defines what Grinta currently supports for official OSS releases.

## Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| Linux | Supported | Required CI gate runs full unit corpus with coverage, then integration/e2e/stress (`gates-on-linux-*`). |
| Windows | Supported | Required CI gate runs `backend/tests/unit`, then integration/e2e/stress (`gates-on-windows`, `gates-on-windows-extended`). |
| macOS | Supported | Required CI gate runs `backend/tests/unit`, then integration/e2e/stress (`gates-on-macos`, `gates-on-macos-extended`). |
| WSL2 (Ubuntu in Windows) | Supported | Linux install inside the distro; repo on `~/`; project may be `/mnt/c`. Not the same as native Windows. See [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md). |

### macOS platform policy

macOS is a supported release platform with required unit and extended CI gates.
The `gates-on-macos` and `gates-on-macos-extended` jobs in
[`.github/workflows/py-tests.yml`](../.github/workflows/py-tests.yml) run on every
PR and on `main`, matching the Linux extended integration/e2e/stress tier.

Contributors on Mac should still run `pytest backend/tests/unit` locally before
opening PRs that touch shell, terminal, or path handling.

## Platform parity gaps

Grinta is **cross-platform by design**, not OS-transparent. The execution layer
routes through `OS_CAPS` and `UnifiedShellSession`, but some capabilities differ
by host OS. Treat this table as the honest parity contract.

| Area | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Core agent loop (read/edit/run/git) | Full | Full | Full (with parity caveats) |
| Interactive terminal (tmux-backed) | Full | Not available natively | Full |
| Interactive terminal (PTY / subprocess fallback) | Available | Limited interactivity | Available |
| Workspace setup scripts | `.grinta/setup.sh` | `.grinta/setup.ps1` preferred; `.grinta/setup.sh` via Git Bash | `.grinta/setup.sh` |
| Git pre-commit hooks | `.grinta/pre-commit.sh` | `.grinta/pre-commit.ps1` preferred; `.grinta/pre-commit.sh` via Git Bash | `.grinta/pre-commit.sh` |
| `sandboxed_local` profile | bubblewrap (`bwrap`) | AppContainer | `sandbox-exec` |
| MCP (local runtime / action client) | Full | Full (HTTP/SSE + allowlisted stdio) | Full |
| MCP (remote action-execution client) | Full | Full when server exposes MCP | Full |
| Default cache directory | System temp (`<temp>/grinta/cache`) | Same | Same |
| CI certification depth | Full unit + coverage + integration/e2e/stress | Full unit + integration/e2e/stress | Full unit + integration/e2e/stress |

When a feature is **limited** rather than **absent**, the runtime logs a warning
and the agent prompt layer (`terminal_contract`) steers the model toward the
active shell contract (`security.windows_shell` on Windows: `bash` vs `powershell`).

**WSL on Windows:** WSL2 is a **supported Linux tier** inside Ubuntu — repo on `~/`, project may be `/mnt/c`. Separate install from native Windows; see [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md).

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
