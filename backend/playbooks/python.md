---
name: python
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /python
  - /py
---

# Python discipline

Use when the user invokes **`/python`** or **`/py`**, or when writing/editing `.py` files.

## Principles

1. **Type Hints**: Always use standard Python type hints (`str`, `int`, `list[str]`, `dict[str, Any]`, `Callable`). Use `from typing import Optional, Union, Any` for older codebases, or `|` operator for Python 3.10+.
2. **Pathlib over os.path**: Use `pathlib.Path` for all file system logic. Never use `os.path.join`.
3. **F-Strings**: Use f-strings (`f"Found {count} items"`) instead of `.format()` or `%`.
4. **Context Managers**: Always use `with` statements for files, locks, network connections, and database sessions. 

## Code Patterns

```python
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Config:
    path: Path
    retries: int = 3

def load_data(filepath: Path | str) -> dict[str, str]:
    target = Path(filepath)
    if not target.exists():
        raise FileNotFoundError(f"Cannot find {target}")
        
    with target.open("r", encoding="utf-8") as f:
        # processing logic...
        return {"status": "ok"}
```

## Anti-Patterns to Avoid

- ❌ Bare `except:` or `except Exception:`. Always catch specific exceptions (e.g., `except KeyError:`).
- ❌ Mutable default arguments (`def func(items=[]):`). Use `def func(items=None): items = items or []`.
- ❌ Print debugging in production code. Use the standard `logging` module.

## Validation
Run `mypy`, `pyright`, or the project's configured type checker after changing Python code. Let the typechecker find edge cases.
