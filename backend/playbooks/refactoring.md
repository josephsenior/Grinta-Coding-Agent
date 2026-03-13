---
name: refactoring
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - refactor
  - refactoring
  - restructure
  - clean up code
  - improve code quality
  - code quality
  - technical debt
---

# Safe Refactoring Patterns

## Golden Rule

**Refactoring must not change behaviour.** Every step should leave tests green.

## 1. Cover Before You Cut

If the code you are refactoring lacks tests, write characterisation tests first:

```python
def test_legacy_function_characterisation():
    """Documents current behaviour; must stay green after refactoring."""
    assert legacy_fn(known_input) == current_output
```

Run the full suite baseline before touching anything:

```bash
pytest -x --tb=short 2>&1 | tee /tmp/before_refactor.txt
```

## 2. Small, Atomic Commits

Each commit should do exactly one thing:

- Extract a function
- Rename a variable
- Move a module
- Remove dead code
- Flatten nested conditionals

Never rename AND move AND simplify in the same commit.

## 3. Common Patterns

### Extract Function

```python
# Before: hard to test, hard to name
def process(data):
    # 40 lines of tangled logic
    ...

# After: each piece is testable and self-documenting
def process(data):
    validated = _validate(data)
    transformed = _transform(validated)
    return _format(transformed)
```

### Replace Magic Number

```python
# Before
if retries > 3:

# After
MAX_RETRIES = 3
if retries > MAX_RETRIES:
```

### Simplify Boolean

```python
# Before
if condition == True:
    return True
else:
    return False

# After
return condition
```

### Guard Clause (Reduce Nesting)

```python
# Before: arrow anti-pattern
def fn(x):
    if x is not None:
        if x > 0:
            if x < 100:
                return x * 2

# After: early return
def fn(x):
    if x is None or x <= 0 or x >= 100:
        return None
    return x * 2
```

## 4. Rename with Confidence

Use IDE rename refactoring (or grep) — never manually hunt-and-replace:

```bash
# Find all usages before renaming
grep -rn "old_name" backend/ --include="*.py"
```

## 5. After Each Step

```bash
pytest -x --tb=short  # must stay green
```

If tests break after a "pure refactor", you changed behaviour — revert and redo more carefully.

## 6. What NOT to Refactor Today

Avoid touching code that:

- Has no tests
- Is about to be deleted
- Is owned by another in-progress PR
- Works correctly and is rarely touched
