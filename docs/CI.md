# Continuous integration

This document describes what runs in GitHub Actions and how it relates to local `pytest` ([`pytest.ini`](../pytest.ini)). **Linux PR gates** run the full **`backend/tests`** tree with coverage (unit + integration + e2e + stress). **Windows** gates still run **`backend/tests/unit`** only for cross-platform smoke.

## Required checks on pull requests

| Workflow | Job | What runs |
|----------|-----|-----------|
| **Run Python Tests** | `gates-on-linux-coverage-{a,b,d,f,g,e,c,report}` + `gates-on-linux-extended` | Unit tests with coverage sharded across seven Linux jobs (execution split into D+F+G; G includes former H/I slices), combined in report; then integration/e2e/stress. |
| **Run Python Tests** | `gates-on-windows` | Same unit corpus as `gates-on-linux` on `windows-latest`. |
| **Run Python Tests** | `gates-on-macos` | Same unit corpus as `gates-on-linux` on `macos-latest` — **advisory only** (`continue-on-error: true`) until the matrix is promoted to required. |
| **Lint** | pre-commit, mypy, version check | See [`.github/workflows/lint.yml`](../.github/workflows/lint.yml). |
| **Dependency Review** | `dependency-review` | Blocks high-severity dependency risk on pull requests. |
| **CodeQL** | `analyze` | Static security analysis for Python on PRs and main. |
| **CLI Regression Tests** | (when paths match) | CLI integration smoke and selected orchestration tests; see [`.github/workflows/e2e-tests.yml`](../.github/workflows/e2e-tests.yml). |
| **Smoke Install** | `smoke-install` | Clean venv wheel install + source onboarding smoke (`scripts/smoke_install.*`, `scripts/smoke_source_onboarding.*`) on Linux and Windows; see [`.github/workflows/smoke-install.yml`](../.github/workflows/smoke-install.yml). |

Codecov upload is enforced (`fail_ci_if_error: true`) and coverage uses the same `fail_under` policy as the project configuration. The coverage gate runs against the full `backend/tests` tree (not unit-only), so integration, e2e, and stress tests contribute to the reported percentage.

## Heavy / integration / benchmark tier

The **Heavy / Integration Tests** job in `py-tests.yml` runs only when:

- the workflow is scheduled,
- manually dispatched, or
- the push is to `main`.

It executes: `pytest backend/tests -m "heavy or integration or benchmark"`.

Markers are defined in `pytest.ini`. That job is marker-filtered over the full tree. A bare local `pytest` (no path arguments) still collects all of `backend/tests` per `testpaths`; narrow with `pytest backend/tests/unit` or add `-m` when you want a smaller slice.

## What to run before opening a PR

See [Contributing — testing](../CONTRIBUTING.md#testing-before-a-pull-request).

## Support stance for announcement copy

For public release messaging, align claims with [Support Matrix](SUPPORT_MATRIX.md):

- Linux and Windows are officially supported (required CI gates).
- macOS is best-effort until promoted from advisory to required.
