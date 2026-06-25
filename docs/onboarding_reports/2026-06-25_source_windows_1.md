# Fresh-machine onboarding report

## Metadata

| Field | Value |
| --- | --- |
| Date | 2026-06-25 |
| Install path | source uv |
| OS | Windows 11 (win32 10.0.26200) |
| Python version | 3.12.10 |
| Grinta version | grinta 1.0.0rc1 |
| Machine | Developer workstation (APP_ROOT isolated smoke via TEMP) |

## Provider setup

| Field | Value |
| --- | --- |
| Provider chosen in `grinta init` | openai (existing repo settings) |
| Model | opencode/mimo-v2.5-free |
| API key source | settings.json / env |

## Checklist

| Step | Pass / fail | Notes |
| --- | --- | --- |
| Install (`bootstrap_env.py dev-test`) | pass | `uv sync` dev-test profile |
| `grinta init` (interactive wizard) | pass | Re-run on existing checkout; wizard writes full security block |
| `grinta` TUI launch | pass | Textual app loads on TTY |
| First agent task (`/health` or starter prompt) | pass | `/health` reports git + rg |
| `grinta doctor` (optional) | pass | Settings schema + tooling checks |

## Friction log

- Env-detected keys now persist to `settings.json` on first launch (Phase 0 fix).
- `grinta doctor` reports missing API key when only env vars are set without persistence — addressed by auto-save.

## Sign-off

- [x] Report reviewed for RELEASE_CHECKLIST.md onboarding gate
