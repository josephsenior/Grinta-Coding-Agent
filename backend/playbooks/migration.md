---
name: migration
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /migration
  - /upgrade
---

# Migration and upgrade playbook

Use for framework upgrades, API contract shifts, schema migrations, and large dependency bumps.

## 1) Build a migration map

- Current state: versions, key APIs used, integration points.
- Target state: versions, required API/behavior changes.
- Breaking surface: compile errors, runtime behavior, config changes.

## 2) Choose strategy

- In-place incremental migration (preferred for low downtime).
- Strangler pattern (new path + controlled traffic shift).
- Big-bang only if the system is small and rollback is trivial.

## 3) Stabilize interfaces first

- Add compatibility wrappers to isolate third-party differences.
- Keep call sites stable while internals move.
- Add contract tests before touching business logic.

## 4) Execute in reversible slices

- One subsystem per PR.
- Feature-flag behavior flips.
- Include rollback instructions in each PR description.

## 5) Verify and harden

- Run focused regression suites per slice.
- Add one end-to-end smoke for the happy path.
- Watch logs/metrics for deprecations and elevated error rates.

## Migration checklist

- Data migration plan present (or explicit "none required").
- Backfill/retry strategy defined.
- Observability added for the new path.
- Old path removal criteria documented.

## Minimal example prompt

`/migration: move from Pydantic v1 patterns to v2 across settings and validation models`
