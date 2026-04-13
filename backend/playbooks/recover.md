---
name: recover
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /recover
---

# Long-session recovery

Use this when a run is stuck, repeatedly failing, or appears to stop making progress.

## 1) Stabilize first

- Stop risky loops and avoid repeated retries with different prompts.
- Capture the latest failing command, error message, and action type.
- Preserve the current state before larger edits.

## 2) Identify failure class

- Stuck loop: same plan or action repeats with no new evidence.
- Circuit-breaker style halt: execution was intentionally paused after repeated failures.
- Context fatigue: responses become generic, contradictory, or ignore recent constraints.

## 3) Recover with smallest reset

- Prefer a focused retry with a tighter target and fewer moving parts.
- Re-run only the failing step first, not the full workflow.
- If recovery fails twice, split the work into smaller checkpoints.

## 4) Re-anchor context

- Restate objective in one paragraph and list current constraints.
- Include only high-signal artifacts (failing tests, exact errors, changed files).
- Avoid dumping large logs unless the error source is unknown.

## 5) Verify before continuing

- Confirm the previous blocker is gone.
- Run one targeted validation, then resume normal flow.
- If issue persists, switch to `/orch-debug` or `/audit`.

## Example: targeted recovery loop

```bash
uv run pytest backend/tests/unit/playbooks/engine/test_playbook_match_trigger.py -q
uv run pytest backend/tests/unit/playbooks/engine/test_playbook_loading.py -q
```

Use the first command to validate trigger behavior and the second to validate loading/type behavior before resuming broader work.
