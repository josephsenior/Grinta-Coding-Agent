# Support Matrix

This matrix defines what Grinta currently supports for official OSS releases.

## Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| Linux | Supported | Required CI gate (`gates-on-linux`). |
| Windows | Supported | Required CI gate (`gates-on-windows`). |
| macOS | Best effort | CI runs in advisory mode (`continue-on-error: true`). |

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
