# Engine (`backend/engine`)

LLM-facing agent logic: prompt assembly, tool definitions, and orchestration of model turns before actions are handed to `backend/orchestration/` and executed in `backend/execution/`.

## Layout

- **`orchestrator.py`** — engine-side coordination for model calls and tool intent in the session loop.
- **`tools/`** — built-in tools (terminal, file edits, search, debugger, etc.) the model can invoke.
- **`prompts/`** — system prompt partials and related prompt assets.

Risk limits, retries, stuck detection, and task validation are implemented in **`backend/orchestration/`**, not in this package.

## References

- [Architecture](../../docs/ARCHITECTURE.md) — end-to-end topology
- [Developer guide](../../docs/DEVELOPER.md) — repository layout and workflows
