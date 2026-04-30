# Release and GA checklist

Use this list before declaring a **1.0.0** (or any major) release and before publishing to PyPI. It aligns with the [CI](CI.md) jobs contributors see on every PR.

## Pre-release verification

- [ ] **Unit tests (full corpus):** `PYTHONPATH=. uv run pytest backend/tests/unit` passes on your machine (same scope as [py-tests workflow](../.github/workflows/py-tests.yml) `gates-on-linux` / `gates-on-windows`).
- [ ] **Lint:** pre-commit and mypy pass (see [lint workflow](../.github/workflows/lint.yml)); run `pre-commit run --all-files` locally if you change Python.
- [ ] **CLI smoke:** from a clean venv or `uv run`, start `grinta` or `uv run python -m backend.cli.entry` and confirm the REPL loads; run [e2e-tests workflow](../.github/workflows/e2e-tests.yml) steps locally if you changed CLI/launch/packaging:
  - `uv run pytest -m integration backend/tests/integration/test_cli_entry_integration.py backend/tests/integration/test_cli_task_e2e.py -q`
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
