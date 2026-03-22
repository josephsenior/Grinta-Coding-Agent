---
name: Testing
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /testing
---

# Testing discipline

Use when the user invokes **`/testing`**. Prefer the **project’s** configured runner (`pytest`, `jest`, `vitest`, etc.).

## Principles

- **AAA:** Arrange → Act → Assert; one logical behaviour per test.
- **Names:** `test_<behaviour>_<condition>` — not `test_foo`.
- **Independence:** No order dependency; each test sets up its own data.
- **Fast feedback:** `pytest path/to/test.py -x -v` or equivalent while iterating.

## Python (pytest) — minimal patterns

```python
import pytest

@pytest.fixture
def db():
    s = make_session()
    yield s
    s.close()

@pytest.mark.parametrize("n,expected", [(2, 4), (3, 9)])
def test_square(n, expected):
    assert n * n == expected

def test_api_mocked():
    with patch("mymod.requests.get") as m:
        m.return_value.json.return_value = {"ok": True}
        assert fetch()["ok"] is True
```

## JS/TS (Vitest/Jest) — minimal patterns

```typescript
import { describe, it, expect, vi } from "vitest";

describe("math", () => {
  it("adds", () => expect(add(2, 3)).toBe(5));
});

it("mocks fetch", async () => {
  global.fetch = vi.fn().mockResolvedValue({ json: () => ({ x: 1 }) });
  expect((await load()).x).toBe(1);
});
```

## React (component)

Use **Testing Library**: render → query by role/label → `userEvent` / `fireEvent` → assert visible state. Prefer stable queries (`getByRole`) over brittle CSS.

## Before merge

Run the **widest** suite the project uses for PRs (full `pytest`, `npm test`, CI parity).
