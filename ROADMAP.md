# Roadmap

This roadmap tracks **post-`v1.0.0-rc1` priorities** for the current terminal product surface.
It intentionally separates **release trust work** from future capability work so maintainers
can improve the project without changing the agent's core behavior.

## Track 1: GA trust and documentation honesty

- Keep root docs, user docs, and release docs aligned with the actual shipped behavior.
- Remove or quarantine stale legacy contributor surfaces that imply an older server-style product.
- Make release notes and support docs explicit about the current support stance, and clearly label historical snapshots when older release notes describe an earlier certification policy.
- Add a lightweight docs-drift pass to every RC and GA checklist.

## Track 2: Repository hygiene and maintainer operations

- Remove tracked cache and machine-local artifact trees from version control.
- Keep build outputs, logs, and temporary evaluation artifacts untracked by default.
- Reduce “mystery meat” maintenance surfaces: if a helper target is legacy, label it clearly or retire it.
- Tighten packaging/release housekeeping so Homebrew, Scoop, PyPI, and source checkouts stay in sync.

## Track 3: Contributor experience

- Keep the happy path obvious: bootstrap, `init`, run, test, release-smoke.
- Prefer a small set of stable helper commands over many overlapping entrypoints.
- Keep contributor docs current with CI reality, especially around platform-specific expectations.
- Expand fresh-machine onboarding reports before broadening the supported matrix.

## Track 4: Reliability follow-through

- Improve first-run onboarding reliability on clean Windows and Linux systems.
- Expand compatibility validation for Python 3.13 and macOS.
- Improve long-session performance and context-compaction observability.
- Expand integration and stress coverage for provider, MCP, and tool-edge cases.

## Community requests

Open feature requests in GitHub Issues using the feature template. High-signal
requests with clear use cases are prioritized first, but release-trust and
maintainer-hygiene work stays ahead of net-new surface area until GA is boring.
