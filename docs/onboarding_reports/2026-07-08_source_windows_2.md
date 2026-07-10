# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-07-08 |
| Install path | source uv |
| OS | Windows 11 |
| Python version | 3.12 |
| Grinta version | 1.0.0rc1 (source checkout) |
| Machine | Developer workstation (automated smoke; not a fresh VM) |
| Evidence type | ci-smoke-only |
| TTY for `grinta init` | no (CI stubs = no) |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | n/a (stub LLM smoke) |
| Model | stub |
| API key source | stub sitecustomize |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`pipx install grinta` or source bootstrap) | pass | `python scripts/bootstrap_env.py base` |
| `grinta init` (interactive wizard) | pass | Non-interactive stdin correctly exits 3 without writing settings |
| `grinta` TUI launch | skip | Automated smoke uses stub CLI task |
| First agent task (`/health` or starter prompt) | pass | `scripts/smoke/run_stub_cli_task.ps1 -UseUvRun` |
| `grinta doctor` (optional) | skip | Not part of this smoke bundle |
| WSL2 layout (`grinta doctor` wsl_* checks, or `scripts/smoke/smoke_wsl_layout.sh`) | n/a | Native Windows run |

## Friction log

- Automated contributor smoke validates source bootstrap and stub agent task; interactive GA still requires fresh VM evidence.
- Run `.\scripts\smoke\smoke_source_onboarding.ps1` from repo root to reproduce.

## Sign-off

- [x] Report reviewed for [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) onboarding gate (ci-smoke evidence only)
