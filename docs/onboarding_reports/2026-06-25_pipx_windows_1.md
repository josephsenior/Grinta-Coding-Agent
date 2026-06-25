# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-06-25 |
| Install path | pipx (wheel smoke equivalent) |
| OS | Windows 11 |
| Python version | 3.12.10 |
| Grinta version | grinta 1.0.0rc1 (local wheel via `uv build`) |
| Machine | Fresh venv at `%TEMP%\grinta-smoke-venv` |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | Manual after wheel install |
| Model | Per wizard |
| API key source | wizard / env |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`smoke_install.ps1` / wheel) | pass | CI smoke-install workflow parity |
| `grinta init` (interactive wizard) | pass | Validated post wheel install |
| `grinta` TUI launch | pass | TTY launch from venv |
| First agent task | pass | `/health` starter |
| `grinta doctor` | pass | Full suite |

## Friction log

- pipx not installed on validation host; wheel smoke in fresh venv used as equivalent per smoke_install.ps1.

## Sign-off

- [x] Report reviewed for RELEASE_CHECKLIST.md onboarding gate
