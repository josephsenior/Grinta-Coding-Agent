# Promotion & Release Workflow

This repository currently follows a **main-branch promotion model**.

There is no separate long-lived beta or staging branch documented in the current tree. In practice, promotion means: stabilize a feature branch through PR review, merge to `main`, run the quality gates that already exist in CI, then cut a versioned release when `main` is in a publishable state.

This document describes the workflow that is actually supported by the repo today.

---

## What Counts as Promotion

Promotion is the point where a change stops being "merged code" and becomes "something we are willing to ship and support."

For Grinta, that usually means all of the following are true:

- the change is merged into `main`
- CI is green on `main`
- local reliability checks have been run for the release candidate
- the version and changelog are updated
- a git tag is created for the release
- container and package publishing steps are either triggered or intentionally deferred

---

## Existing Quality Gates

These are the concrete gates already present in the repository.

| Gate | File | Purpose |
| --- | --- | --- |
| Python tests | `.github/workflows/py-tests.yml` | Syntax checks, lockfile validation, minimal pytest coverage on PRs and `main` |
| Lint + type checks | `.github/workflows/lint.yml` | Pre-commit, version consistency, mypy |
| End-to-end tests | `.github/workflows/e2e-tests.yml` | Agent loop E2E coverage on Linux and Windows |
| Container build | `.github/workflows/ghcr-build.yml` | Build/test/push container images for PRs, `main`, and tags |
| Package release | `.github/workflows/pypi-release.yml` | Manual publish flow with pre-release tests |
| Evaluation runs | `.github/workflows/run-eval.yml` | Label-driven, release-driven, or manual evaluation passes |
| Local reliability gate | `backend/scripts/verify/reliability_gate.py` | Phase-based release gate runnable from the Makefile |

Two local commands matter most before promotion:

```bash
make reliability-gate
make reliability-gate-integration
```

The first runs the full reliability gate. The second adds integration coverage and is the stronger pre-release check.

---

## Promotion Checklist

Before cutting a release from `main`, verify all of the following:

- PR review is complete and the final branch has already merged cleanly into `main`
- CI is green on `main`
- `make reliability-gate` passes locally
- `make reliability-gate-integration` passes for releases that touch runtime, orchestration, or evaluation-critical code
- `CHANGELOG.md` is updated
- `pyproject.toml` version is updated
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

- `pyproject.toml`
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

Tagging is the clean boundary between "merged" and "released."

### 5. Let the automated workflows do their work

After merge/tag:

- container build and push happen through `.github/workflows/ghcr-build.yml`
- evaluation can run through `.github/workflows/run-eval.yml`
- package publishing is available through the manual PyPI workflow

The PyPI publish flow is not fully automatic. Treat it as an explicit operator action, not an assumed side effect.

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
