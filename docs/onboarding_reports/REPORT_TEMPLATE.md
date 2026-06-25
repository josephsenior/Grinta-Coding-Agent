# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | YYYY-MM-DD |
| Install path | pipx / source uv / docker |
| OS | Linux / Windows / macOS + version |
| Python version | |
| Grinta version | `grinta --version` or PyPI tag |
| Machine | Fresh VM / hardware (no prior `~/.grinta`) |
| Evidence type | `interactive-fresh-machine` or `ci-smoke-only` |
| TTY for `grinta init` | yes / no (CI stubs = no) |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | |
| Model | |
| API key source | env / wizard / local (Ollama/LM Studio) |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`pipx install grinta-ai` or source bootstrap) | | |
| `grinta init` (interactive wizard) | | |
| `grinta` TUI launch | | |
| First agent task (`/health` or starter prompt) | | |
| `grinta doctor` (optional) | | |

## Friction log

- 
- 

## Screenshots / logs

(Optional paths or links to redacted logs.)

## Sign-off

- [ ] Report reviewed for [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) onboarding gate
