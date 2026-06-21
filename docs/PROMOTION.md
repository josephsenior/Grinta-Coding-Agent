# Promotion & Release Workflow

This repository currently follows a **main-branch promotion model**.

There is no separate long-lived beta or staging branch documented in the current tree. In practice, promotion means: stabilize a feature branch through PR review, merge to `main`, run the quality gates that already exist in CI, then cut a versioned release when `main` is in a publishable state.

This document describes the workflow that is actually supported by the repo today. The step-by-step release and GA checklist lives in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

---

## What Counts as Promotion

Promotion is the point where a change stops being "merged code" and becomes "something we are willing to ship and support."

For Grinta, that usually means all of the following are true:

- the change is merged into `main`
- CI is green on `main`
- local reliability checks have been run for the release candidate
- the version and changelog are updated
- a git tag is created for the release
- package publishing is triggered manually; container images are published only when a maintainer dispatches the Docker workflow

---

## Existing Quality Gates

These are the concrete gates already present in the repository.

| Gate | File | Purpose |
| --- | --- | --- |
| Python tests | `.github/workflows/py-tests.yml` | Lockfile validation, sharded unit coverage (75%), integration/e2e/stress on Linux, required unit gates on Windows and macOS |
| Lint + type checks | `.github/workflows/lint.yml` | Pre-commit, version consistency, mypy |
| CodeQL | `.github/workflows/codeql.yml` | Static security analysis for Python |
| Bandit | `.github/workflows/bandit.yml` | Python SAST |
| Dependency review | `.github/workflows/dependency-review.yml` | Blocks high-severity dependency risk on PRs |
| End-to-end tests | `.github/workflows/e2e-tests.yml` | CLI/orchestration regression when paths match |
| Smoke install | `.github/workflows/smoke-install.yml` | Wheel + source onboarding smoke on Linux and Windows |
| Container build | `.github/workflows/ghcr-build.yml` | **Manual dispatch only** — Docker assets may be absent; do not assume images publish with a tag |
| Package release | `.github/workflows/pypi-release.yml` | **Manual** publish flow with pre-release tests (mypy + unit tests, wheel smoke) |
| Evaluation runs | `.github/workflows/run-eval.yml` | Label-driven, release-driven, or manual evaluation passes |
| Local reliability gate | `backend/scripts/verify/reliability_gate.py` | Phase-based release gate runnable from the Makefile |
| Stress suite | `make test-stress` | Parallel pending, backpressure, and event-stream load tests (`pytest -m stress`) |

Two local commands matter most before RC and GA promotion:

```bash
make reliability-gate
make reliability-gate-integration
```

The first runs the full reliability gate. The second adds integration coverage, the reliability integration bundle, and the stress suite — the stronger pre-release check for RC and GA.

CI's `gates-on-linux-extended` already runs integration, e2e, and stress on every PR; the Makefile targets above are additional local confidence for release cuts.

---

## Promotion Checklist

Before cutting a release from `main`, work through [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). At minimum:

- PR review is complete and the final branch has already merged cleanly into `main`
- all **required** CI jobs are green on `main` (see checklist table)
- `make reliability-gate` passes locally for RC/GA releases
- `make reliability-gate-integration` passes for releases that touch runtime, orchestration, or evaluation-critical code
- `CHANGELOG.md` is updated
- `pyproject.toml` version and `_DEFAULT_VERSION` in `backend/__init__.py` are updated together
- release notes are clear enough that a user can understand what changed and what risk exists

If a change affects evaluation, autonomy, prompt behavior, or safety, promotion should also include a deliberate evaluation run rather than relying only on unit and E2E tests.

---

## Recommended Promotion Flow

### 1. Stabilize the candidate on `main`

Promotion should start only after the feature branch is merged and `main` is green.

Do not tag a release while `main` is red.

### 2. Run the local gates

Use the repo's existing Make targets:

```bash
make reliability-gate
make reliability-gate-integration
```

If the second command is too expensive for a tiny docs-only or packaging-only change, note that explicitly in the release PR or release notes.

### 3. Update versioned metadata

Update these files together:

- `pyproject.toml` (`version = "x.y.z"`)
- `backend/__init__.py` (`_DEFAULT_VERSION` fallback)
- `CHANGELOG.md`

The current package version lives in `pyproject.toml`, and the changelog should reflect the exact user-visible contents of the release.

### 4. Tag the release

Create and push a version tag from `main`.

```bash
git checkout main
git pull --ff-only
git tag vX.Y.Z
git push origin main --tags
```

Tagging is the clean boundary between "merged" and "released." It does **not** automatically publish to PyPI or GHCR.

### 5. Publish artifacts (operator actions)

After the tag is on `main`:

1. **PyPI** — trigger the manual [pypi-release workflow](../.github/workflows/pypi-release.yml). It runs mypy + unit tests, builds the wheel, smoke-tests `grinta --help` / `--version`, then publishes via OIDC to the `pypi` environment.
2. **Scoop / Homebrew** — update manifests with the **published** sdist URL and checksums from PyPI **after** upload (see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).
3. **Container images** — trigger [ghcr-build](../.github/workflows/ghcr-build.yml) manually if Docker assets are present and an image is needed. This workflow is **not** tied to tag push.
4. **Evaluation** — run [run-eval](../.github/workflows/run-eval.yml) manually or via release trigger when the release touches autonomy, prompts, safety, or orchestration.
5. **Release notes** — publish via GitHub Releases / [release-drafter](../.github/release-drafter.yml), aligned with [Support Matrix](SUPPORT_MATRIX.md) claims.

### 6. Run evaluation when the release deserves it

The repo already supports evaluation labels on PRs and release/manual triggers in CI.

Use the label-driven options when you want promotion evidence before a merge:

- `run-eval-1`
- `run-eval-2`
- `run-eval-50`
- `run-eval-100`

Use the release-triggered or manual workflow when you want a post-tag confidence pass.

---

## When to Be Stricter

Promotion should be stricter than normal merges when a change touches:

- orchestration or state transitions
- tool execution or edit application
- prompt assembly or autonomy behavior
- safety policy or command classification
- context compaction or replay/evaluation behavior
- packaging, install, or runtime bootstrap

Those are the areas most likely to make the product look healthy while silently becoming less trustworthy.

---

## Rollback Expectations

Rollback depends on what has already happened:

- **Merged but not tagged:** revert on `main`
- **Tagged but not published:** delete or supersede the tag, then cut a corrected release
- **Container already pushed:** re-promote a corrected tag or publish a follow-up patch release
- **PyPI already published:** do not rely on deletion; publish a new fixed version

The safest rollback story is still a patch release with clear notes.

---

## What This Workflow Intentionally Does Not Pretend

This repo does **not** currently document:

- a formal beta branch model
- a long-lived staging environment
- automated semantic-release choreography
- a zero-touch publish pipeline for every artifact

That is fine.

The honest workflow is better than an imaginary enterprise process diagram. Grinta already has enough quality gates to support disciplined releases. The right next step is to use them consistently, not to invent a bigger ceremony than the repository actually runs.
