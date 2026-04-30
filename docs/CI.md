# Continuous integration

This document describes what runs in GitHub Actions and how it relates to local `pytest` defaults ([`pytest.ini`](../pytest.ini)).

## Required checks on pull requests

| Workflow | Job | What runs |
|----------|-----|-----------|
| **Run Python Tests** | `gates-on-linux` | Full unit corpus: `pytest backend/tests/unit` (same discovery as local `pytest` with default `testpaths`). |
| **Run Python Tests** | `gates-on-windows` | Same full unit corpus on `windows-latest`. |
| **Run Python Tests** | `gates-on-macos` | Same full unit corpus on `macos-latest` — **advisory only** (`continue-on-error: true`) until the matrix is promoted to required. |
| **Lint** | pre-commit, mypy, version check | See [`.github/workflows/lint.yml`](../.github/workflows/lint.yml). |
| **CLI Regression Tests** | (when paths match) | CLI integration smoke and selected orchestration tests; see [`.github/workflows/e2e-tests.yml`](../.github/workflows/e2e-tests.yml). |

Codecov upload is best-effort (`fail_ci_if_error: false`) so a registry outage does not block merges; the test step still fails on real test failures.

## Heavy / integration / benchmark tier

The **Heavy / Integration Tests** job in `py-tests.yml` runs only when:

- the workflow is scheduled,
- manually dispatched, or
- the push is to `main`.

It executes: `pytest -m "heavy or integration or benchmark"`.

Markers are defined in `pytest.ini`. Default local `pytest` does **not** include those unless you opt in.

## What to run before opening a PR

See [Contributing — testing](../CONTRIBUTING.md#testing-before-a-pull-request).
