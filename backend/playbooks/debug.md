---
name: debug
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - bug fix
  - fix bug
  - debug
  - debugging
  - traceback
  - exception
  - error fix
  - investigate error
---

# Systematic Debugging Approach

## 1. Reproduce First

Before touching code, reliably reproduce the bug:

```bash
# Run the failing test or command that exposes the issue
pytest tests/path/to/failing_test.py -x -v
```

Never attempt a fix you can't verify works.

## 2. Read the Full Traceback

Work from the **bottom up**:
- Last frame = where the crash happened
- First frame = the entry point
- Look for your own code (not library internals) first

## 3. Narrow the Blast Radius

```python
# Add a minimal reproduction before fixing
def test_bug_repro():
    # Smallest possible input that triggers the problem
    result = broken_function(minimal_input)
    assert result == expected_value  # this fails
```

## 4. Hypothesis → Verify Loop

1. **State a hypothesis**: "I think X happens because Y"
2. **Add a log or assertion** to test it — do NOT change logic yet
3. **Run** and observe
4. **Confirm or discard** — don't move to a fix until the root cause is clear

```python
import logging
logger = logging.getLogger(__name__)

# Temporary diagnostic logging
logger.debug("state before call: %s", repr(state))
result = suspect_function(state)
logger.debug("state after call: %s", repr(result))
```

## 5. Fix and Validate

- Make the **smallest possible change** that fixes the root cause
- Re-run the original reproduction case — it must pass
- Run the full test suite to catch regressions:

```bash
pytest -x --tb=short
```

## 6. Common Root Causes by Symptom

| Symptom | Likely cause |
|---|---|
| `AttributeError: 'NoneType'` | Unchecked `None` return from a function |
| `KeyError` | Missing dict key — use `.get(key)` or guard |
| `IndexError` | Off-by-one or empty list assumption |
| `RecursionError` | Missing base case or mutual recursion |
| `TypeError: argument after **` | Dict passed where kwargs expected |
| Intermittent failure | Race condition or non-deterministic ordering |
| Works locally, fails in CI | Missing env var, different Python version, or path issue |

## 7. Add a Regression Test

After fixing, add a test that would have caught this bug:

```python
def test_regression_issue_123():
    """Regression: broken_function used to crash when given empty list."""
    result = broken_function([])
    assert result == default_value
```
