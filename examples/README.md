# Examples

Reproducible task transcripts. Each example is a self-contained prompt you
can paste into the REPL after `START_HERE.ps1` (Windows) or `./start_here.sh`
(macOS / Linux).

## 1 — Python project: refactor + run tests

> Refactor `backend/utils/string_utils.py` to expose a single
> `slugify(text: str) -> str` helper, update all callers, and run
> `pytest backend/tests/unit/utils/test_string_utils.py` to confirm.

Expected behaviour:

* `read` + `grep_search` to find current callers
* one or two `text_editor` actions
* one `terminal_run` invocation that exits 0
* `/cost` afterwards reports a small (< $0.05 with default model) spend

## 2 — JavaScript project: add a route + smoke test

Pre-req: a Node project at `./web/` with `npm test` wired.

> Add a `GET /healthz` route in `web/src/server.ts` that returns
> `{ ok: true }`, write a Vitest case that asserts the response, and run
> `npm test --prefix web`.

## 3 — Debugger: pause on exception, inspect locals

> Use the debugger to launch `examples/debug_target.py`, set a breakpoint at
> the line that raises `ValueError`, and read the local variables on hit.

`examples/debug_target.py`:

```python
"""Tiny program for the debugger walkthrough."""

def parse_age(value: str) -> int:
    age = int(value)
    if age < 0:
        raise ValueError(f'negative age not allowed: {age}')
    return age


if __name__ == '__main__':
    parse_age('-5')
```

Expected behaviour with the new debugger reliability work:

* Cold start (first `debugger` call in the session) completes in
  ~2-5 s on Windows; subsequent calls reuse the warmed adapter.
* `app.log` shows: `DAP: spawning adapter`, `DAP: initialize sent`,
  `DAP: launch sent`, `DAP: configurationDone ack`, `DAP: ready in N s`.
* If the adapter cannot start, the returned `ErrorObservation` includes
  the adapter's stderr tail so the model knows what went wrong.

Run `/health` first if your machine has not used the debugger before — it
pre-imports `debugpy.adapter` and verifies `rg` + `git` are on PATH.
