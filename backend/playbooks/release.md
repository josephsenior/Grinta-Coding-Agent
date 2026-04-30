---
name: release
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /release
---

# Release readiness and rollout

Use this before tagging or shipping to reduce last-minute regressions.

## 1) Define scope

- Identify included commits/features and known exclusions.
- Confirm version bump and changelog intent match actual changes.

## 2) Validate quality gates

- Run required tests, lint, and type checks for touched surfaces.
- Confirm migration or config changes are backward compatible (or documented as breaking).

## 3) Operational checks

- Verify env variables, secrets, and runtime dependencies exist in target environments.
- Confirm rollback path and on-call visibility (logs/alerts/health checks).

## 4) Rollout plan

- Choose rollout style: full, staged, or canary.
- Define explicit stop/rollback criteria before deployment starts.

## 5) Post-release verification

- Check key user flows and error/latency signals immediately after deploy.
- Record release notes with links to PRs, incidents, and follow-ups.
