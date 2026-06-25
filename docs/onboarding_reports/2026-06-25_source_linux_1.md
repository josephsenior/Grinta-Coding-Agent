# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-06-25 |
| Install path | source uv |
| OS | Linux (CI runner — GitHub Actions) |
| Python version | 3.12 |
| Grinta version | grinta 1.0.0rc1 |
| Machine | CI smoke_source_onboarding.sh |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | N/A (automated non-TTY guard) |
| Model | N/A |
| API key source | stub task harness |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`bootstrap_env.py base`) | pass | smoke_source_onboarding.sh |
| `grinta init` non-TTY guard | pass | Exit 3, no settings write |
| `grinta --help` | pass | |
| Stub CLI task | pass | run_stub_cli_task.sh |
| Interactive init + TUI | pending manual | Requires human GA refresh on Linux VM |

## Friction log

- Automated CI covers non-interactive path; interactive GA evidence requires dedicated Linux VM run.

## Sign-off

- [x] Report reviewed for RELEASE_CHECKLIST.md onboarding gate (automated slice)
