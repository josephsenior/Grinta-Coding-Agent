---
name: orch_debug
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /orch-debug
---

# Orchestration debugging

Use this when failures appear to come from orchestration flow rather than one tool call.

## 1) Pin the failing stage

- Determine whether failure happened in step decision, action execution, observation handling, or validation.
- Capture the exact action and observation pair around the failure.

## 2) Inspect service boundaries

- Check the service chain involved in the failing step.
- Verify assumptions moving between services (inputs, outputs, state transitions).
- Look for divergence between expected and actual step transitions.

## 3) Trace state transitions

- Compare state before and after the failing step.
- Validate guard conditions that should have blocked or allowed the transition.
- Confirm retry logic did not mask the first root error.

## 4) Isolate and reproduce

- Reproduce with the smallest command path that still fails.
- Add one focused assertion or log to prove the hypothesis.
- Avoid broad instrumentation that floods signal.

## 5) Confirm stability

- Run the focused test path first.
- Run one adjacent workflow to catch regression at service boundaries.

## Example: focused orchestration checks

```bash
uv run pytest backend/tests/unit/orchestration -q
uv run pytest backend/tests/unit/playbooks -q
```

Start with orchestration tests, then verify recall/playbook paths still behave as expected.
