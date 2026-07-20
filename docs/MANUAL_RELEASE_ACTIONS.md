# Manual Actions Required Before Grinta v1.0.0

The repository can enforce artifact, test, and tag integrity, but the following controls require maintainer or platform access.

## 1. GitHub ruleset for `main`

Create an active branch ruleset targeting `main`:

- Require pull requests before merging.
- Require at least one approval when another trusted reviewer is available.
- Require conversation resolution.
- Require branches to be up to date before merging.
- Require every release-relevant Actions check, including all jobs from Lint, Python Tests, Integration, CLI Regression, Smoke Install, CodeQL, Bandit, and dependency audit/review.
- Block force pushes and branch deletion.
- Do not allow routine maintainer bypass. Reserve emergency bypass for a separately documented incident procedure.

Confirm the ruleset by opening a deliberately failing test PR and verifying that GitHub refuses the merge.

## 2. PyPI ownership and Trusted Publishing

- Confirm that the `grinta` project name is controlled by the intended PyPI account/organization.
- In PyPI, add a Trusted Publisher for this repository, workflow `.github/workflows/pypi-release.yml`, and environment `pypi`.
- In GitHub, create the `pypi` environment and require maintainer approval before deployment.
- Do not add a long-lived PyPI API token unless OIDC is unavailable during a documented recovery.

## 3. Interactive GA evidence

Complete and commit 12 fresh-machine reports using `docs/onboarding_reports/REPORT_TEMPLATE.md`:

- 3 × pipx/Linux
- 3 × pipx/Windows
- 3 × source/Linux
- 3 × source/Windows

Add separate WSL2 evidence before continuing to call WSL2 supported. Reports must capture OS, Python version, exact commit/artifact, commands, first launch, provider setup, task result, restart/resume behavior, logs, and defects.

## 4. Seven-day green window

Honor the policy in `docs/RELEASE_CHECKLIST.md`: start the clock only after all required checks and interactive evidence are green. Any release-blocking regression restarts the window. Revise the policy in a reviewed PR instead of silently ignoring it.

## 5. Final metadata PR

Only after the gates above pass, atomically change all RC metadata to `1.0.0`, including:

- `pyproject.toml` version and `Development Status :: 5 - Production/Stable`
- `uv.lock`
- `backend/__init__.py` fallback version
- README, changelog, citation, architecture/support docs, package-manager manifests, and issue/release documentation

Run `.github/scripts/verify_release_tag.py --tag v1.0.0 --require-stable` before merging.

## 6. Release media and history

- Upload the backed-up demo recording, preview, and any evidence archive as GitHub Release assets; do not put them back in the source tree or Python distributions.
- Consider removing the deleted binaries from Git history before v1.0.0. History rewriting is disruptive: coordinate it, back up refs, notify contributors, and require fresh clones afterward.

## 7. Release execution

After the exact GA commit has completed the green window:

1. Create and push a signed `v1.0.0` tag from that exact commit. The tag push triggers the protected PyPI workflow.
2. Approve the `pypi` environment only after the workflow has built once and smoke-tested the exact wheel and sdist on Linux and Windows.
3. Confirm the PyPI installation on clean Linux and Windows machines.
4. Create GitHub Release `Grinta 1.0 — First Stable Release`, not marked pre-release.
5. Attach the tested wheel, sdist, `SHA256SUMS`, release notes, demo media, and evidence assets. Enable immutable releases.
6. Update Homebrew and Scoop only after the final PyPI/GitHub URLs and hashes exist.
