---
name: ci
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /ci
---

# CI triage and stabilization

Use this when CI is red and you need the fastest path back to green without masking real failures.

## 1) Read the first failing job end-to-end

- Capture the exact failing step, command, and error text.
- Ignore downstream failures until the first root failure is understood.

## 2) Reproduce locally with the same command

- Run the closest local equivalent (same test target, lint command, Python/Node version when possible).
- If local does not reproduce, compare env assumptions: paths, OS, cache, secrets, and matrix versions.

## 3) Classify the failure

- Deterministic code regression.
- Flaky test or timeout.
- Infra/config drift (dependency, image, runner, permission).

## 4) Fix with the smallest safe change

- Prefer deterministic fixes over retries.
- If flake is proven, quarantine with a clear TODO and owner.
- Update configs and docs when changing CI behavior.

## 5) Verify before closing

- Re-run focused checks first, then the full relevant suite.
- Include a concise "root cause + fix + verification" note in the PR.
