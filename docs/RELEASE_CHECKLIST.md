# Release and GA checklist

Use this list before declaring a **1.0.0** (or any major) release and before publishing to PyPI. It aligns with the [CI](CI.md) jobs contributors see on every PR.

## Pre-release verification

- [ ] **Linux gate (full corpus):** `PYTHONPATH=. uv run pytest --cov=backend --cov-fail-under=75 backend/tests` passes on your machine (same scope as [py-tests workflow](../.github/workflows/py-tests.yml) `gates-on-linux`).
- [ ] **Windows gate (unit smoke):** `PYTHONPATH=. uv run pytest backend/tests/unit` passes (same scope as `gates-on-windows`).
- [ ] **Reliability gate (RC / GA):** `make reliability-gate` passes; for release candidates and GA promotion also run `make reliability-gate-integration` (adds integration + stress suites via [`reliability_gate.py`](../backend/scripts/verify/reliability_gate.py)).
- [ ] **Stress suite (RC / GA):** `make test-stress` or `PYTHONPATH=. uv run pytest backend/tests/stress -m stress -q` passes (parallel pending lifecycle, event-stream backpressure, durable-writer load).
- [ ] **Integration suite (RC / GA):** `make test-integration` or `PYTHONPATH=. uv run pytest backend/tests/integration -m integration -q` passes (includes hung-action recovery, persistence health, trajectory regression).
- [ ] **Optional — full Python test tree:** `PYTHONPATH=. uv run pytest` from the repo root (discovers `backend/tests` per [`pytest.ini`](../pytest.ini); long run; may need services). Run before a major release if you want confidence beyond the unit gates.
- [ ] **Lint:** pre-commit and mypy pass (see [lint workflow](../.github/workflows/lint.yml)); run `pre-commit run --all-files` locally if you change Python.
- [ ] **CLI smoke:** from a clean venv or `uv run`, start `grinta` or `uv run python -m backend.cli.entry` and confirm the Textual app loads on a TTY; run [e2e-tests workflow](../.github/workflows/e2e-tests.yml) steps locally if you changed CLI/launch/packaging:
  - `uv run pytest -m integration backend/tests/integration/test_cli_entry_integration.py backend/tests/integration/test_cli_task_e2e.py -q`
- [ ] **Smoke install (automated):** [smoke-install workflow](../.github/workflows/smoke-install.yml) is green on the PR (wheel + source onboarding scripts on Linux and Windows).
- [ ] **Fresh-machine onboarding (manual):** complete the reports in [FRESH_MACHINE_ONBOARDING.md](FRESH_MACHINE_ONBOARDING.md) before GA (3× pipx, 3× source `uv`; Docker optional).
- [ ] **macOS (advisory):** [py-tests macOS job](../.github/workflows/py-tests.yml) is `continue-on-error: true` — before calling macOS “supported”, check the latest run is green or run `pytest backend/tests/unit` on a Mac.

## Version and packaging bump (when the above are green)

1. Set `version = "x.y.z"` in [`pyproject.toml`](../pyproject.toml).
2. Mirror the fallback strings in [`backend/__init__.py`](../backend/__init__.py) if the install path cannot read metadata.
3. Update [packaging/scoop/grinta.json](../packaging/scoop/grinta.json) and [packaging/homebrew/grinta.rb](../packaging/homebrew/grinta.rb) with the **published** sdist URL and checksums from PyPI **after** upload (not before the artifact exists).
4. Update the version hint in the bug issue form ([`bug_template.yml`](../.github/ISSUE_TEMPLATE/bug_template.yml)) if you maintain it per release.
5. Record changes in `CHANGELOG.md` and tag the release in Git.
6. Review and update [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) to reflect current dependency attribution workflow.

**Note:** Bumping `pyproject.toml` to `1.0.0` without updating Scoop/Homebrew URLs to a real `grinta-ai-1.0.0` sdist will break those manifests until PyPI has that artifact.

## macOS stance

macOS CI is **informational** until the team promotes it to a required check. Document any known gaps in the release notes rather than treating a green Linux/Windows matrix as macOS certification.

## GA promotion criteria (RC -> 1.0.0)

Use this gate when deciding whether to move from a public RC to an official GA tag:

- [ ] **Required CI stays green for a sustained window:** Linux + Windows required jobs and lint are green on `main` for at least 7 consecutive days.
- [ ] **CLI onboarding confidence:** at least 3 fresh-machine install + `grinta init` + first-task reports complete successfully across supported install paths (`pipx` required; source `uv run` required; Docker optional). Use the table in [FRESH_MACHINE_ONBOARDING.md](FRESH_MACHINE_ONBOARDING.md); automated partial coverage runs in [smoke-install workflow](../.github/workflows/smoke-install.yml).
- [ ] **RC feedback triage complete:** all high-severity RC feedback issues are either fixed and verified or explicitly documented as post-GA follow-up.
- [ ] **Docs match real behavior:** `README.md`, `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md`, and `docs/SUPPORT_MATRIX.md` reflect the exact current CLI UX and platform support stance.
- [ ] **Packaging artifacts validated:** PyPI package install path, Scoop, and Homebrew metadata are verified against the published artifacts for the target version.
- [ ] **Known limitations are explicit:** any remaining gaps (for example macOS best-effort caveats) are clearly listed in release notes and support docs.
