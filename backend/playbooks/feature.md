---
name: feature
type: knowledge
version: 2.1.0
agent: Orchestrator
triggers:
  - /feature
---

# Structured feature work

Align with system **EXECUTION_DISCIPLINE** and **TASK_MANAGEMENT**. Use this when the user asks you to implement a new feature.

## 1. Discover & Plan
Read existing code for patterns, similar features, and data flow **before** writing new code.
- Write a short `.plan.md` or output a numbered list to the user verifying the steps.
- Avoid repeated directory listings. Use targeted `grep` and file reads.

## 2. Shape the API / Interfaces
Sketch types/signatures, database schemas, and expected error cases **before** filling in the bodies.
- If the required inputs/outputs look fragile, stop and fix the design first.

## 3. Tests
Add tests that describe acceptance criteria.
- Run them to see them fail (**red**).
- Implement the feature body to make them pass (**green**).
- Prefer the project’s real test stack (`pytest`, `vitest`, etc.).

## 4. Integrate
Check routes, schemas, config files, exports, and docs in the **same** change set. A feature isn't done if it expects the user to wire it up to the router manually.

## 5. Review & Finalize
- Run a full test run.
- Lint/typecheck if configured.
- Ensure no secrets were logged or hardcoded.
- Ask the user if they want you to commit the feature `git commit -m "feat: <description>"`.
