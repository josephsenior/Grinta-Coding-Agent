---
name: hardened
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /hardened
---

# Hardened execution workflow

Use this when working in semi-trusted repositories or when command risk must be minimized.

## 1) Classify risk before execution

- Low risk: read-only inspections, listing, static analysis.
- Medium risk: local builds/tests with controlled inputs.
- High risk: networked scripts, broad file writes, destructive commands.

## 2) Prefer safe-first actions

- Start with read-only diagnostics.
- Narrow file scope before any mutation.
- Avoid commands that modify global environment or system state.

## 3) Require explicit evidence for risky actions

- State why the action is needed.
- State expected outcome and rollback path.
- Run the smallest safe variant first.

## 4) Protect sensitive data

- Never print secrets in command output or comments.
- Use environment variables for credentials.
- Redact tokens and private endpoints in summaries.

## 5) Verify and document

- Confirm the intended result with focused checks.
- Record one-line lesson if the workflow exposed a new risk pattern.

## Example: safe-first command sequence

```bash
uv run pytest backend/tests/unit/playbooks/engine/test_types.py -q
uv run pytest backend/tests/unit/playbooks/engine/test_playbook_match_trigger.py -q
```

Run targeted, read-focused validation before broader operations.
