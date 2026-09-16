# `tui/renderer/` — decomposition guide

The TUI event renderer is decomposed into three sibling directories:

* `mixins/` — a single mixin class per concern, **mixed into `TUIRenderer`**.
  These define the *public surface* of the renderer and may call each
  other freely. They own lifecycle (mount, drain, finalize) and
  cross-cutting display logic.

* `handlers/` — per-action-kind handler functions, called by
  `RendererEventProcessorMixin._process_event` based on the event type.
  Each module is one domain (`file.py`, `shell.py`, `terminal.py`, …) and
  exports a small set of top-level functions. They are **stateless and
  side-effecting** — they mount or update widgets and return nothing.

* `helpers/` — pure formatting / parsing utilities, no side effects, no
  widget access. Examples: diff parsing, file-path normalization, Rich
  text builders. Reusable from both mixins and handlers.

## When to add new code

* If you're adding a new event-source kind (e.g. a new tool) → put the
  handler in `handlers/<domain>.py` and import it from
  `RendererEventProcessorMixin._process_event`.
* If you're adding a new lifecycle method (init, mount, drain) → put it
  on the appropriate `mixins/<concern>.py`.
* If you're adding a pure formatter → put it in `helpers/<domain>.py`.

If a new domain needs both a handler and helper modules, **prefer
keeping each in its own file** even if they're tiny — this matches the
existing layout and keeps the per-domain split consistent.

## What NOT to do

* Don't add state to `handlers/` — they're meant to be event-driven
  one-shots. State lives in `TUIRenderer` (or the `Screen`) and is
  initialized in `__init__`.
* Don't reach across domains in `handlers/` (e.g. `file.py` shouldn't
  import from `terminal.py`). Cross-domain orchestration belongs in
  the mixins.
* Don't duplicate rendering logic between `tui/renderer/handlers/` and
  `cli/event_rendering/` (the Rich non-TUI renderer). They are separate
  implementations on purpose; share *data* through `TUIRenderer`'s
  state, not code.

## Responsiveness

Screen drain and history-load messages schedule screen-owned workers and return
immediately. Workers still apply widget changes on the Textual event loop; only
render preparation and ledger reads run in threads. The renderer's async lock
serializes live dispatch and history replay. Clear Transcript invalidates work
that was already preparing content.

Streaming preparation reuses complete fenced blocks and applies each text
snapshot once. Final snapshots form coalescing boundaries. Queue pressure removes
only interim streaming snapshots and null observations; meaningful events may
temporarily exceed the queue's soft limit. Backlog compaction uses a linear pass.

Unified diffs use `DiffLines`, a line-API widget that draws only visible rows.
The enclosing diff view keeps the existing compact/detail scrolling behavior.
Gutters, semantic colors, selection, and the complete supplied diff stay available.
This virtualizes diff rows; transcript-level card pruning is still a separate
mechanism. Pruning replaces history references to removed widgets with source
content so Copy Transcript does not keep detached DOM trees alive.

Diagnostics in the `grinta.tui` debug log:

- `tui_loop_lag_ms`: event-loop stalls above 100 ms, sampled twice a second.
- `tui_slow_event`, `prep_ms`, `dispatch_ms`: events taking at least 50 ms.
- `tui_drain_ms`, `tui_pending_depth`: every drain pass, including backlog passes.

Run `python -m backend.tests.manual.tui_performance` in the project environment
to compare the former per-row widget tree with virtual lines. It makes no provider
calls. On this Windows workspace, a 1,000-row headless comparison measured 5,001
versus 2 descendants, 8,835 versus 95 ms to display, and 1,786 versus 47 ms to
scroll. These are isolated benchmark results, not live-session latency guarantees.
