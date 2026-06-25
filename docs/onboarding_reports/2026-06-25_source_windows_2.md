# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-06-25 |
| Install path | source uv |
| OS | Windows 11 |
| Python version | 3.12.10 |
| Grinta version | grinta 1.0.0rc1 |
| Machine | Clean APP_ROOT under `%TEMP%\grinta-source-smoke-app` |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | N/A (non-TTY guard only) |
| Model | N/A |
| API key source | N/A |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`bootstrap_env.py base`) | pass | smoke_source_onboarding.ps1 step 1 |
| `grinta init` (non-interactive guard) | pass | Exit 3, no settings.json written without TTY |
| `grinta --help` | pass | Entry point responds |
| Stub CLI task | pass | `run_stub_cli_task.ps1` deterministic LLM |
| `grinta doctor` | pass | After settings present |

## Friction log

- PowerShell smoke script treats init stderr as terminating error when `$ErrorActionPreference = Stop` — cosmetic script issue, exit code still 3.

## Sign-off

- [x] Report reviewed for RELEASE_CHECKLIST.md onboarding gate
