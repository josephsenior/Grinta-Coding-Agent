---
name: perf
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /perf
  - /profile
---

# Performance profiling

Use when the user invokes **`/perf`** or **`/profile`**. Golden rule:
**measure before you change anything.** Optimize the proven hot path, not the
one you assume is slow.

## 1. Establish a baseline

- Pick one reproducible workload (a command, request, or test) and time it a
  few runs to get a stable number.
- Record the baseline before touching code so you can prove an improvement.

```bash
python -X importtime -c "import yourmodule"   # import-time cost
hyperfine "your-command --workload"            # stable wall-clock timing
```

## 2. Profile to find the hot path

```bash
# Python: deterministic profile, sorted by cumulative time
python -m cProfile -s cumtime script.py | head -30

# Python: low-overhead sampling on a running process (no code change)
py-spy top --pid <PID>
py-spy record -o profile.svg --pid <PID>      # flame graph

# Node: built-in profiler
node --prof app.js                            # then: node --prof-process isolate-*.log
```

## 3. Read the profile

- Sort by **cumulative** time to find expensive call trees, then by **total**
  (self) time to find the actual hot function.
- Look for the usual suspects: work inside loops, N+1 queries, repeated I/O,
  re-computation that could be cached, and accidental O(n^2) growth.

## 4. Optimize one bottleneck

- Change the single biggest contributor first; re-measure before the next.
- Prefer algorithmic wins (better data structure, batching, caching) over
  micro-optimizations.
- Keep correctness: the test suite must stay green after each change.

## 5. Prove the win

- Re-run the **same** baseline workload and report before/after numbers.
- If the gain is marginal or hurts readability, revert. Note the result so the
  next person doesn't retry the same dead end.
