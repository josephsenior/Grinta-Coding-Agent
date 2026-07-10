# Continuous integration

This document describes what runs in GitHub Actions and how it relates to local `pytest` ([`pytest.ini`](../pytest.ini)).

**Linux PR gates** shard the full **unit** corpus (`backend/tests/unit`) across six coverage jobs, enforce **75%** in `gates-on-linux-coverage-report`, then run integration, e2e, and stress in `gates-on-linux-extended`. **Windows** and **macOS** run the full unit corpus, then the same integration/e2e/stress extended tier after unit gates pass.

For release tagging and GA promotion, see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

## Required checks on pull requests

| Workflow | Job | What runs |
|----------|-----|-----------|
| **Run Python Tests** | `gates-on-linux-coverage-{a,b,c,d,g,e}` + `report` | Full unit corpus on Linux with sharded coverage; combined report enforces **75%** (`--fail-under=75`). Execution shards (D/G) skip `compileall`; syntax is gated on other shards. |
| **Run Python Tests** | `gates-on-linux-extended` | Integration, e2e, and stress suites on Linux (runs after the coverage report job passes). |
| **Run Python Tests** | `gates-on-windows` (3.12 + 3.13) | Full unit corpus cross-platform smoke. |
| **Run Python Tests** | `gates-on-windows-extended` | Integration, e2e, and stress suites on Windows (runs after unit gates pass; Python 3.12). |
| **Run Python Tests** | `gates-on-macos` | Full unit corpus on macOS. |
| **Run Python Tests** | `gates-on-macos-extended` | Integration, e2e, and stress suites on macOS (runs after unit gate passes). |
| **Run Python Tests** | `gates-on-linux-py313` | Full unit corpus on Python 3.13 (runs after Linux extended). |
| **Lint** | pre-commit, mypy, version check | See [`.github/workflows/lint.yml`](../.github/workflows/lint.yml). |
| **CodeQL** | `analyze` | Static security analysis for Python on PRs and main. |
| **Security Scan (Bandit)** | Bandit | Python SAST; fails on medium/high findings. See [`.github/workflows/bandit.yml`](../.github/workflows/bandit.yml). |
| **Dependency Review** | `dependency-review` | Blocks high-severity dependency risk on pull requests. |
| **Dependency Audit (pip-audit)** | `pip-audit` | Audits locked runtime dependencies for known CVEs. |
| **CLI Regression Tests** | (when paths match) | CLI integration smoke and selected orchestration tests; see [`.github/workflows/e2e-tests.yml`](../.github/workflows/e2e-tests.yml). |
| **Smoke Install** | `smoke-install` | Clean venv wheel install + source onboarding smoke (`scripts/smoke/smoke_install.*`, `scripts/smoke/smoke_source_onboarding.*`) on Linux and Windows; see [`.github/workflows/smoke-install.yml`](../.github/workflows/smoke-install.yml). |

### Advisory (not release-blocking today)

| Job | Notes |
| --- | --- |
| **Heavy / Integration Tests** | Marker-filtered `heavy \| integration \| benchmark` slice; runs on `main`, schedule, and manual dispatch only. |

### Coverage

The **75%** gate applies to the **unit** corpus only, measured across sharded Linux jobs and combined in `gates-on-linux-coverage-report`. Integration, e2e, and stress suites run in `gates-on-linux-extended`, `gates-on-windows-extended`, and `gates-on-macos-extended` but do **not** contribute to the coverage percentage.

Codecov upload runs from the coverage report job with `fail_ci_if_error: false` (upload failure does not block the merge). The enforced threshold is the local `coverage report --fail-under=75` step in CI, matching [`pyproject.toml`](../pyproject.toml).

## Heavy / integration / benchmark tier

The **Heavy / Integration Tests** job in `py-tests.yml` runs only when:

- the workflow is scheduled,
- manually dispatched, or
- the push is to `main`.

It executes: `pytest backend/tests -m "heavy or integration or benchmark"`.

Markers are defined in `pytest.ini`. That job is marker-filtered over the full tree. A bare local `pytest` (no path arguments) still collects all of `backend/tests` per `testpaths`; narrow with `pytest backend/tests/unit` or add `-m` when you want a smaller slice.

## Local equivalents

| CI job | Local command |
| --- | --- |
| Linux unit + coverage | `PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests/unit` |
| Windows unit smoke | `PYTHONPATH=. uv run pytest backend/tests/unit` |
| Integration / e2e / stress | `PYTHONPATH=. uv run pytest backend/tests/integration backend/tests/e2e backend/tests/stress` |
| Lint | `pre-commit run --all-files` and `uv run mypy --config-file mypy.ini` |

## What to run before opening a PR

See [Contributing — testing](../CONTRIBUTING.md#testing-before-a-pull-request).

## Support stance for announcement copy

For public release messaging, align claims with [Support Matrix](SUPPORT_MATRIX.md):

- Linux, Windows, and macOS are officially supported with unit gates plus extended integration/e2e/stress coverage on all three platforms.
