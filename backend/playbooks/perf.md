---
name: perf
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /perf
---

# Performance and cost profiling

Use this to reduce latency, token usage, and expensive retries.

## 1) Measure before changing

- Pick one scenario and capture baseline runtime and output size.
- Record model/provider and command path used.

## 2) Identify hot spots

- Large prompts or repeated full-context calls.
- Repeated failed tool calls followed by broad retries.
- Overly wide test runs during tight iterations.

## 3) Apply low-risk optimizations

- Prefer targeted tests during iteration; run wide suites before merge.
- Reduce redundant context in intermediate steps.
- Reuse proven commands and artifacts instead of re-discovery.

## 4) Re-measure and compare

- Keep optimization only if it improves speed or token usage without lowering quality.
- Revert micro-optimizations that add complexity without measurable gain.

## 5) Guard against regressions

- Add one benchmark-like validation command in your workflow notes.
- Track whether future changes increase runtime significantly.

## Example: practical profiling loop

```bash
uv run pytest backend/tests/unit/playbooks/engine/test_playbook_loading.py -q
uv run pytest backend/tests/unit/playbooks/engine/test_playbook_loading.py -q -k invalid_type
```

Use one broad-enough baseline and one focused subset to compare iteration speed.
