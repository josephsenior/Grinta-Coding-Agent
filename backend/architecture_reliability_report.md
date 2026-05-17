# Grinta Architecture & Reliability Report

This report consolidates deep architectural findings of bugs, leaks, race conditions, and inconsistencies discovered in the CLI-to-backend integration, Orchestrator Event Lifecycle, and Persistence layers. These issues uniquely threaten agent stability and reliability during extended/long coding sessions.

## 1. Orchestration & Event Lifecycle Bugs

### A. Deadlocks & Concurrency Traps (`backend/orchestration/session_orchestrator.py`)
1. **Parallel Retry Infinite Loop (`_try_parallel_read_batch`)**:
   Under the `_try_parallel_read_batch` execution logic, tools that crash return `BaseException`. If an exception occurs, the orchestrator triggers an `ErrorObservation` into the stream, yet **re-inserts** the failed actions dynamically back into the pending action pipeline via a hardcoded iteration index (`pending.insert(index, action)`). The agent then serially forces re-execution of these guaranteed-failing calls in an infinite cycle.
2. **Missing Await Mutability Sync**:
   `pending.insert()` triggers immediately after `await asyncio.gather(...)` finishes. During this `await` timeline, background context modifications (e.g. `_reset()` fired by `Ctrl+C` interrupt from the CLI) can flush the queue. Re-inserting elements assumes the list state remained static, breaking execution ordering.
3. **Improper Loop Isolation (`_step_lock`)**:
   `self._step_lock = asyncio.Lock()` operates out-of-context in constructor instantiation prior to robust event loop coupling. If the true main event loop shifts (common in CLI headless vs TUI mode jumps), this lock abandons execution guardrails.

### B. Memory/Context Accumulation Leak
1. **Fake Condensation Limits**:
   In `_handle_post_execution()`, the system gauges memory pressure. If limit breaks hit `CRITICAL`, it correctly logs it and calls `record_condensation()`. However, **it never condenses `self.state.history`.** The payload list strictly balloons to infinity. By applying strict throttling limits (`set_memory_pressure_factor()`) repeatedly against an infinitely expanding payload, it forcibly starves and eventually permanently halts the agent.

## 2. Persistence & Runtime Reliability Issues

### A. Thread Safety & SQLite Desyncs (`backend/persistence/sqlite_event_store.py`)
1. **Concurrent Read Segfaults**:
   `_get_read_conn()` spins up a single bare SQLite read-only connection passed via `check_same_thread=False` and immediately exposes it naked to all internal read accesses (`list_events`, `count`) without thread-locks. Heavy worker orchestration will pipeline interweaved queries into the same cursor handle, resulting safely varying between `OperationalError: database is locked` and outright program segmentation faults.
2. **Uncommitted Write Orphans**:
   The store's mutation commands like `delete_event()` execute raw string writes instantly followed by `conn.commit()`. Due to a complete absence of `try-except-rollback` handling on the local statements, any disk or constraint error during the execution leaves the local connection's write buffer jammed with a corrupted open transaction. Follow-up state checks will stall permanently on the hung lock.
3. **Payload Out Of Memory (OOM)**:
   Persisted `json.loads(row['payload'])` runs identically regardless of sequence sizes. With no byte bounds nor history truncation enabled, heavily hallucinated outputs or massive `diff` chunks in long sessions will OOM spike RAM long before context window guards kick in.

## 3. CLI & Middleware Pipeline Flaws

### A. Environment Race Conditions (`backend/cli/main.py`)
1. **The "Too-Late" Override Bug**:
   `_load_dotenv_early()` strictly evaluates based on CLI triggers via `sys.argv`. In headless testing or dynamic SDK consumption of `main(project='folder')`, core singletons load first. `LOG_TO_FILE` / LLM flags statically snapshot before the configuration payload reads the explicitly provided `.env` path rendering project properties ineffective over global scopes.

### B. Rollback Checkpoint Eviction (`backend/orchestration/session_orchestrator.py`)
1. **`active_to_closing` & `init_to_active` GC Sweeps**:
   The Orchestrator injects `_create_phase_boundary_checkpoint` to anchor core transitions (like initial starts and closing snapshots). However, underneath, `RollbackManager` strictly caps at `max_checkpoints=30` accompanied by generic `auto_cleanup=True`. Over a prolonged sequence of normal IDE agent shell interactions, regular checkpoints consume the stack limits, violently vacuuming the underlying crucial `init_to_active` backup data out of existence. Consequently, "Restarting" a long running session becomes mathematically impossible as the bedrock gets routinely scavenged mapping.

### C. Worker Controller Memory Leaker (`backend/orchestration/services/event_router_service.py`)
1. **Eventual Leaks in Delegate Pipelines**:
   If an orchestrated multi-agent worker throws a structural setup failure within its local `_step_inner()`, it routes straight to the `except:` tree. Because `worker_controller.close(set_stop_state=False)` is linearly located inside the primary try success trail instead of a `finally` block, it permanently abandons its thread, stream, and unclosed SQLite file handlers as uncollectible background ghosts hanging idle continuously.
