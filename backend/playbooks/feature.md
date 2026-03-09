---
name: feature
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - implement feature
  - add feature
  - new feature
  - feature implementation
  - build feature
---

# Structured Feature Development

## 1. Understand Before Building

Read the relevant existing code before writing a single line:

- What data flows in and out?
- What existing patterns does the codebase use?
- Is there a similar feature already implemented?

```bash
# Find related code
grep -r "related_term" backend/ --include="*.py" -l
```

## 2. Design the Interface First

Write the function/class signature with types, not the body:

```python
def new_feature(
    input_data: InputType,
    config: FeatureConfig,
) -> OutputType:
    """One-sentence description of what this does.

    Args:
        input_data: What it processes
        config: Configuration controlling behaviour

    Returns:
        What the caller gets back
    """
    raise NotImplementedError
```

Review the signature before implementing. If it feels awkward, the design is wrong.

## 3. Write the Test First

```python
def test_new_feature_happy_path():
    result = new_feature(valid_input, default_config)
    assert result.status == "success"
    assert result.value == expected_value

def test_new_feature_edge_case():
    result = new_feature(empty_input, default_config)
    assert result.status == "empty"
```

Run the tests to confirm they **fail** before implementing.

## 4. Implement in Small Steps

1. Make the simplest thing that could possibly work
2. Run tests after each meaningful chunk
3. Refactor only once tests are green

```bash
# Run just the new tests while building
pytest tests/unit/test_new_feature.py -x -v
```

## 5. Integration Points

Check every place the feature connects to the rest of the system:

- [ ] API route added or updated?
- [ ] Schema/model updated?
- [ ] Settings/config field added if configurable?
- [ ] Import added to `__init__.py`?
- [ ] Docs updated?

## 6. Before Marking Done

```bash
# Full suite — no regressions
pytest -x --tb=short

# Type check
mypy backend/path/to/new_module.py

# Lint
ruff check backend/path/to/new_module.py
```
