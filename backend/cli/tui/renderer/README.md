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
