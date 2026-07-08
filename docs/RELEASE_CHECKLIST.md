# Release and GA checklist

Use this list before cutting a **release candidate**, **patch/minor**, or **GA** tag and before publishing to PyPI. Aligns with [CI.md](CI.md).

**Do not tag while `main` is red.** Wait for required checks on the commit you intend to ship.

---

## Required CI on `main` (automated)

These workflows run on every PR and on pushes to `main`. All **required** jobs must be green on the release commit before you tag.

| Workflow | Jobs | What they cover |
| --- | --- | --- |
| **Run Python Tests** | `gates-on-linux-coverage-{a,b,c,d,g,e}` + `report` | Full unit corpus on Linux with sharded coverage; combined report enforces **75%** (`--fail-under=75`). Execution shards (D/G) skip `compileall`; syntax is gated on other shards. |
| **Run Python Tests** | `gates-on-linux-extended` | Integration, e2e, and stress suites on Linux (runs after the coverage report job passes). |
| **Run Python Tests** | `gates-on-windows` (3.12 + 3.13) | Full unit corpus cross-platform smoke. |
| **Run Python Tests** | `gates-on-windows-extended` | Integration, e2e, and stress suites on Windows (runs after unit gates pass; Python 3.12). |
| **Run Python Tests** | `gates-on-macos` | Full unit corpus on macOS. |
| **Run Python Tests** | `gates-on-macos-extended` | Integration, e2e, and stress suites on macOS (runs after unit gate passes). |
| **Run Python Tests** | `gates-on-linux-py313` | Full unit corpus on Python 3.13 (runs after Linux extended). |
| **Lint** | pre-commit, mypy, version consistency | See [`.github/workflows/lint.yml`](../.github/workflows/lint.yml). |
| **CodeQL** | Python analysis | Static security analysis. |
| **Security Scan (Bandit)** | Bandit | Python SAST. |
| **Dependency Review** | PR dependency diff | Blocks high-severity dependency risk (PRs). |
| **Dependency Audit (pip-audit)** | pip-audit | Audits locked runtime dependencies for known CVEs. |
| **Smoke Install** | Linux + Windows | Wheel + source onboarding smoke — see [`.github/workflows/smoke-install.yml`](../.github/workflows/smoke-install.yml). |
| **CLI Regression Tests** | When paths match | CLI/orchestration regression — see [`.github/workflows/e2e-tests.yml`](../.github/workflows/e2e-tests.yml). |

**Advisory (not release-blocking today):**

| Job | Notes |
| --- | --- |
| **Heavy / Integration Tests** | Marker-filtered `heavy \| integration \| benchmark` slice; runs on `main`, schedule, and manual dispatch only. |

See [CI.md](CI.md) for the full matrix and local equivalents.

---

## Pre-release verification (local)

Run these on the release commit (or the PR branch right before merge) in addition to trusting CI.

### Always (any release)

- [ ] **`main` CI green:** all required jobs above pass on GitHub for the target commit.
- [ ] **Linux unit + coverage (optional local mirror):**

```bash
uv run python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests/unit
```

CI already shards unit coverage across six Linux jobs and enforces 75% in `gates-on-linux-coverage-report`; run this locally when debugging coverage gaps.

- [ ] **Windows unit smoke (optional local mirror):**

```bash
uv run python scripts/bootstrap_env.py dev-test
PYTHONPATH=. uv run pytest backend/tests/unit
```

- [ ] **Lint:** `pre-commit run --all-files` and `uv run mypy --config-file mypy.ini` (same scope as the Lint workflow).
- [ ] **Source tree hygiene:** no tracked cache/build/runtime artifacts on the release branch (`pip/`, `dist/`, local logs, stale wheels, stray `__pycache__`). See `.gitignore`.
- [ ] **CLI smoke:** from a clean venv or `uv run`, confirm `grinta --help` and that the Textual app loads on a TTY (`uv run python -m backend.cli.entry`). If you changed CLI/launch/packaging, also run:

```bash
uv run pytest -m integration backend/tests/integration/test_cli_entry_integration.py backend/tests/integration/test_cli_task_e2e.py -q
```

- [ ] **Smoke install (automated in CI):** confirm [smoke-install workflow](../.github/workflows/smoke-install.yml) is green; local equivalents:

```bash
uv build --wheel
WHEEL_DIR=./dist ./scripts/smoke_install.sh
./scripts/smoke_source_onboarding.sh
```

### RC / GA (stronger gates)

CI’s `gates-on-linux-extended`, `gates-on-windows-extended`, and `gates-on-macos-extended` jobs already run integration, e2e, and stress on every PR. For RC and GA promotion, also run the local reliability bundles:

- [ ] **Reliability gate:** `make reliability-gate` ([`reliability_gate.py`](../backend/scripts/verify/reliability_gate.py)).
- [ ] **Reliability gate + integration/stress:** `make reliability-gate-integration` (adds integration and stress suites).
- [ ] **Stress suite (spot-check):** `make test-stress` or `PYTHONPATH=. uv run pytest backend/tests/stress -m stress -q`.
- [ ] **Integration suite (spot-check):** `make test-integration` or `PYTHONPATH=. uv run pytest backend/tests/integration -m integration -q`.
- [ ] **Fresh-machine onboarding evidence:** keep reports in [onboarding_reports/](onboarding_reports/) current (3× pipx, 3× source). Track in [GA_GATE_STATUS.md](onboarding_reports/GA_GATE_STATUS.md). CI smoke does not cover interactive first run — **do not tag `v1.0.0` until GA gate is green.**
- [ ] **WSL2 certification (when claiming WSL support):** clone on Linux home, `<project>` may be on `/mnt/c`, `scripts/smoke/smoke_wsl_layout.sh` + interactive report per [QUICK_START.md — WSL](QUICK_START.md#wsl-ubuntu).
- [ ] **Evaluation (when behavior-sensitive):** run [run-eval workflow](../.github/workflows/run-eval.yml) manually if the release touches autonomy, prompts, safety, or orchestration.

### Optional — full Python test tree

```bash
PYTHONPATH=. uv run pytest
```

Discovers all of `backend/tests` per [`pytest.ini`](../pytest.ini). Long run; may need services. Use before a major release for extra confidence beyond the PR gates.

---

## Version and packaging bump

When verification above is green:

1. Set `version = "x.y.z"` in [`pyproject.toml`](../pyproject.toml).
2. Update `_DEFAULT_VERSION` in [`backend/__init__.py`](../backend/__init__.py) — fallback when metadata/pyproject cannot be read at import time.
3. Record changes in `CHANGELOG.md`.
4. Update the version hint in the bug issue form ([`bug_template.yml`](../.github/ISSUE_TEMPLATE/bug_template.yml)) if you maintain it per release.
5. Review and update [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) when dependencies changed materially.
6. **After PyPI upload:** update [packaging/scoop/grinta.json](../packaging/scoop/grinta.json) and [packaging/homebrew/grinta.rb](../packaging/homebrew/grinta.rb) with the **published** sdist URL and checksums from PyPI (not before the artifact exists).

**Note:** Bumping `pyproject.toml` without updating Scoop/Homebrew URLs to a real published sdist will break those manifests until PyPI has that artifact.

---

## Tag and publish

1. **Tag from `main`:**

```bash
git checkout main
git pull --ff-only
git tag vX.Y.Z
git push origin main --tags
```

2. **PyPI:** trigger the manual [pypi-release workflow](../.github/workflows/pypi-release.yml). It runs mypy + unit tests, builds the wheel, smoke-tests `grinta --help` / `--version`, then publishes via OIDC to the `pypi` environment. Publishing is **not** automatic on tag push.
3. **Container images:** the [Docker workflow](../.github/workflows/ghcr-build.yml) is **manual dispatch only** (Docker assets may be absent). Do not assume images publish with the tag.
4. **Release notes:** use GitHub Releases / [release-drafter](../.github/release-drafter.yml) draft or write notes that match [Support Matrix](SUPPORT_MATRIX.md) claims.

---

## macOS stance

macOS is a supported release platform with required unit and extended CI gates
(`gates-on-macos`, `gates-on-macos-extended`) on every PR and on `main`. Before
making shell/path/terminal-heavy public claims, confirm the latest macOS jobs are
green and run a local Mac smoke when practical. Document known platform parity
gaps in release notes (see [Support Matrix](SUPPORT_MATRIX.md)).

---

## GA promotion criteria (RC → 1.0.0)

Use this when deciding whether to move from a public RC to an official GA tag:

- [ ] **Required CI stays green for a sustained window:** Linux, Windows, and macOS required jobs plus lint are green on `main` for at least 7 consecutive days.
- [ ] **CLI onboarding confidence:** fresh-machine reports in [onboarding_reports/](onboarding_reports/); CI: [smoke-install workflow](../.github/workflows/smoke-install.yml).
- [ ] **RC feedback triage complete:** all high-severity RC feedback issues are fixed and verified or explicitly documented as post-GA follow-up.
- [ ] **Docs match real behavior:** `README.md`, `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md`, and `docs/SUPPORT_MATRIX.md` reflect current CLI UX, platform support, and completion-validation behavior.
- [ ] **Packaging artifacts validated:** PyPI install path, Scoop, and Homebrew metadata verified against published artifacts for the target version.
- [ ] **Known limitations are explicit:** remaining gaps (for example Python 3.13 advisory coverage on Linux or platform-specific shell/terminal parity) are listed in release notes and support docs.
