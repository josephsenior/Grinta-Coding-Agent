# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-06-25 |
| Install path | source uv |
| OS | Linux (CI runner) |
| Python version | 3.12 |
| Grinta version | grinta 1.0.0rc1 |
| Machine | CI gates-on-linux + smoke-install |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | stub / manual refresh |
| Model | stub |
| API key source | test harness |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install | pass | PR CI green on main |
| `grinta init` | pass | Non-TTY guard in CI |
| TUI launch | pass | Integration CLI entry tests |
| First task | pass | test_cli_task_e2e integration |
| `grinta doctor` | pass | unit + CLI tests |

## Friction log

- Second Linux source report — confirms CI reproducibility across shards.

## Sign-off

- [x] Report reviewed for RELEASE_CHECKLIST.md onboarding gate
