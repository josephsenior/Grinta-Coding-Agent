# Reliability & Trust Model

This document describes the reliability primitives that ship with Grinta and
is **deliberately honest** about what is and is not guaranteed. Read it before
deploying Grinta against a production codebase.

## Trust model (no automatic sandbox)

Grinta is a **single-user local CLI agent**. It runs as the same OS user that
launched it and inherits that user's filesystem and network permissions. There
is no per-command sandbox, no firejail, and no Docker isolation by default.
This is a deliberate UX trade-off: a sandbox would give up "feels native" speed
and break common workflows (asdf, pyenv, npm scripts, native debuggers).

What protects you instead:

* **Workspace scoping.** File reads/writes outside the workspace root are
  rejected by `path_validation.py`; symlinks and Windows junctions cannot be
  used to escape the workspace.
* **Command risk classification.** Dangerous patterns (`rm -rf /`, `git push
  --force`, `sudo`, recursive deletes outside the workspace, etc.) are flagged
  and gated.
* **Secret masking.** Provider keys and credentials are masked in logs and
  observations before they reach the model or the persisted event stream.
* **Risk-aware blast radius warnings.** Edits across many files trigger an
  inline warning that the model surfaces in its observation.

If you need stronger isolation, run Grinta inside a container or VM you
manage. The CLI itself is not a sandbox.

## Circuit breaker & recovery

`CircuitBreaker` adapts to repeated identical failures from a tool: after a
threshold it stops re-issuing the same call and surfaces a recovery prompt to
the model. Recovery rounds are preserved across intervening housekeeping
actions so the agent does not lose context on an unrelated tool result.

* **Null-action recovery.** When the model returns no actionable tool call
  the controller injects a recovery prompt rather than looping.
* **Pending-action timeouts.** Two tiers: short-running tools default to
  120 s, long-running interactive tools (debugger, terminal) default to 600 s.
  Per-tool timeouts in `backend/core/constants.py` (`TOOL_BRIDGE_TIMEOUT_*`)
  are sourced from a single place and respect any explicit `action.timeout`.

## Debugger latency contract

The DAP debugger (`backend/execution/debugger.py`) is one of the slowest tools
because it spawns a real `debugpy.adapter` subprocess. The runtime ships with
three reliability primitives specifically for that path:

1. **Off-loaded sync work.** `action_execution_server_io.py::debugger` runs
   `DAPDebugManager.handle` via `asyncio.to_thread`, so the event loop is
   never blocked during cold start.
2. **Granular progress logging.** Every DAP step (`spawning adapter`,
   `initialize`, `launch`, `initialized event`, `configurationDone`,
   `ready in N s`) emits an INFO log line so "frozen" becomes "visibly
   working".
3. **Optional warmup.** When `GRINTA_DEBUGPY_WARMUP=1` (default on) the
   in-process runtime pre-imports `debugpy.adapter` in a background thread so
   the first real `debugger` call avoids cold-import latency.

Failure path: if the adapter cannot start, the returned `ErrorObservation`
includes the **adapter's stderr tail** so the model can react meaningfully
instead of seeing a bare `DAPError`.

## Crash & shutdown contract

* **EventStream.** Closed on `/quit`, `Ctrl-C`, and on uncaught exceptions
  via the global handler in `backend/core/logger.py`.
* **Worker pool.** The `ThreadPoolExecutor` used by `call_async_from_sync` is
  shut down at interpreter exit (`atexit`) with `cancel_futures=True` so the
  process exits promptly even with stuck non-daemon threads.
* **Asyncio loop teardown.** `_LOOP_FINALIZE_WAIT_SEC` (default 3 s) caps the
  time spent in `loop.shutdown_asyncgens()` and `loop.shutdown_default_executor()`
  per sync-bridge call, and is now skipped entirely when the loop never
  scheduled either, so simple sync tools do not pay a 5 s tail.
* **DAP cleanup.** Adapter subprocesses are torn down on `start()` failure,
  on dispatch failure, and on `DAPDebugManager.close_all()` (called at
  REPL exit).

## What to do when something goes wrong

* **Hung tool call.** Open `logs/workspaces/<ws>/app.log` and look for the
  most recent `_handle_action START` and the matching `END`. If you see the
  new `DAP: …` lines, the debugger is working through its handshake. If you
  see no progress for > 30 s, copy the tail and file an issue.
* **Wedged debug session.** Run `/health` in the REPL — it verifies that
  `debugpy.adapter` is importable and reports `git`/`rg` availability.
* **Provider failure.** The agent retries with exponential back-off; the UI
  may show compact messages while some transient classes are kept out of the
  model transcript (`notify_ui_only`). Use `/cost` to see cumulative spend
  before retrying.

## Late runtime errors after user stop

Memory/runtime status callbacks can still fire **after** the user stops the
agent or after a **finished** run. Those diagnostics are recorded on the
controller (`set_last_error`, logs), but Grinta **does not** transition
`STOPPED → ERROR` or `FINISHED → ERROR`: that would conflate a deliberate
terminal with a broken session and could break WAL/reconnect semantics.
See `backend/orchestration/runtime_late_error_guard.py`, early status
handling in `backend/core/bootstrap/main.py`, and
`backend/core/bootstrap/agent_control_loop.py`.

## Two kinds of rate limiting

* **LLM provider limits (TPM/RPM/429).** Grinta’s inference client and
  `RecoveryService` / retry queue handle back-off; optional HUD toasts may
  appear. Grinta does **not** require Redis or any other in-repo store for
  that path.
* **Application / API rate limits.** If the project you are editing throttles
  its own HTTP surface (in-memory, gateway, database-backed, etc.), that is
  separate infrastructure: it does **not** fix provider 429s on the agent’s
  model calls.

## Edit verification (grounding gate)

After an edit is followed by **failing** feedback (tests, linters, etc.),
`ActionExecutionService` can require a **grounding** read or terminal check
before further writes or `finish`. Default is strict for safety; relaxing it
(e.g. more edits before the gate, or narrower path rules) is a deliberate
product trade-off—see `backend/orchestration/services/action_execution_service.py`
and `step_guard_service.py`.

## What this document does not promise

* No guarantee against a malicious model intentionally destroying files in
  the workspace. Use git checkpoints (auto-created on every successful
  edit) to recover.
* No guarantee against a malicious MCP server. Only enable MCP servers you
  trust.
* No guarantee that long-running terminals will behave identically across
  PowerShell, bash, and zsh. Behaviour is normalised through the PTY layer
  but extreme cases (TUIs that probe terminal capabilities aggressively) may
  need explicit mode hints.
