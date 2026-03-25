---
name: debug
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /debug
---

# Systematic debugging

Use this when the user explicitly invokes **`/debug`**. For **shell/tool failures**, follow system **ERROR_RECOVERY** first.

## 1. Reproduce

Run the smallest command or test that fails every time. Do not “fix” what you cannot re-run.

## 2. Traceback

Read **bottom-up**: innermost frame where the exception is raised → outward to your code. Prefer frames from the workspace over library frames.

## 3. Shrink

Add a **minimal repro** (tiny test or script) that fails for one reason only.

## 4. Hypothesis loop

State one hypothesis → add logging or assertions → run → confirm or discard before changing production logic.

## 5. Fix + regression

Smallest change that fixes root cause; add a regression test that would have failed before the fix.

## Symptom → likely cause (cheat sheet)

| Symptom | Check |
|--------|--------|
| `NoneType` attribute | Unchecked `None` |
| `KeyError` | Missing key; `.get` / guard |
| `IndexError` | Empty sequence / off-by-one |
| Intermittent | Ordering, time, shared state |
| CI-only | Env, Python version, paths |
