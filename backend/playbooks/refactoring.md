---
name: refactoring
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /refactor
---

# Safe refactoring

**Golden rule:** Behaviour unchanged; tests stay green after every step. Use **task_tracker** for multi-step refactors (system prompt).

## Before edits

- If coverage is weak, add **characterisation** tests that lock current behaviour.
- Baseline: `pytest -x --tb=short` (or project test command) — all green.

## During edits

- **One mechanical change per commit** (extract function *or* rename *or* move file — not all at once).
- Prefer IDE/symbol rename over manual replace.
- Re-run tests after each step.

## Patterns (prefer when they simplify)

- **Extract function** — long blocks → named helpers with clear inputs/outputs.
- **Guard clauses** — early `return` / `continue` instead of deep nesting.
- **Named constants** — magic numbers/strings at module scope.

## Stop

Skip refactors when code has **no tests** and you cannot add any, when the area is **scheduled for deletion**, or when a **parallel PR** owns the same files.
