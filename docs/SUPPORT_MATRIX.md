# Support Matrix

This matrix defines what Grinta currently supports for official OSS releases.

## Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| Linux | Supported | Required CI gate (`gates-on-linux`). |
| Windows | Supported | Required CI gate (`gates-on-windows`). |
| macOS | Best effort | CI runs in advisory mode (`continue-on-error: true`). |

### macOS platform policy

Grinta **ships and accepts contributions on macOS**, but macOS is not a
release-blocking platform until the `gates-on-macos` job is promoted from
advisory to required in [`.github/workflows/py-tests.yml`](../.github/workflows/py-tests.yml).

Until then:

- Treat macOS failures in CI as **signal, not a merge blocker**.
- Do not claim macOS is fully certified in release notes unless the macOS gate
  has been green for the same sustained window as Linux and Windows (see
  [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).
- Contributors on Mac should still run `pytest backend/tests/unit` locally before
  opening PRs that touch shell, terminal, or path handling.

Promotion criteria for required macOS CI: seven consecutive green days on
`main`, no open P0 macOS-only issues, and release notes updated to list macOS
as supported (same bar as Linux/Windows in this matrix).

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

Grinta is supported as a **CLI-first coding agent**. Legacy server-era references in
historical docs/changelog entries should not be treated as current supported product
surfaces.
