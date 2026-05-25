---
name: premerge
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /premerge
  - /shipcheck
---

# Pre-merge quality gate

Use before opening or merging a PR to maximize confidence with minimal churn.

## 1) Scope and intent check

- Confirm the diff matches the stated task.
- Remove opportunistic edits not required for this change.
- Ensure naming and module boundaries follow local conventions.

## 2) Correctness gate

- Run targeted tests for changed behavior.
- Run typecheck/lint for touched modules.
- Verify edge cases: empty input, invalid input, timeout/retry paths.

## 3) Operational gate

- Confirm logging is actionable and not noisy.
- Ensure errors include enough context to debug quickly.
- Confirm no secrets/tokens appear in code, tests, or fixtures.

## 4) UX and API gate

- For UI: keyboard flow, focus states, spacing/readability, narrow viewport sanity.
- For APIs: response shape, status codes, backward compatibility expectations.
- For CLI/TUI: command discoverability and graceful failure messages.

## 5) PR readiness output

- Risk level: low/medium/high.
- What changed.
- What was validated (commands/tests).
- Known limitations and follow-ups.

## Minimal example prompt

`/premerge: run final quality gate on this branch and list remaining risk`

