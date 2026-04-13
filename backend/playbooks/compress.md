---
name: compress
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /compress
---

# Context window and compaction

Use this when sessions become long and response quality drops.

## 1) Detect compaction need

- Repeated reminders of already-known constraints.
- Growing prompt payload with little new signal.
- Model starts ignoring recent high-priority instructions.

## 2) Keep only high-value context

- Current goal and acceptance criteria.
- Current blockers and exact errors.
- Modified files and pending validations.

## 3) Drop low-value context

- Redundant status chatter.
- Repeated command output with no new signal.
- Historical exploration that no longer affects decisions.

## 4) Rebuild concise state

- Create a short state summary: objective, constraints, next 3 actions.
- Preserve concrete evidence links (errors, failing tests, changed files).
- Continue with targeted commands only.

## 5) Validate post-compaction quality

- Ensure the next response respects constraints and uses the new summary.
- If quality is still degraded, switch to `/recover` and split work.

## Example: compact state template

```text
Objective: Add new playbooks and remove deprecated ones.
Constraints: Keep client package; no destructive git operations.
Evidence: playbook inventory, trigger coverage tests, changed files list.
Next actions: update docs -> run tests -> finalize summary.
```
