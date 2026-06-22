"""Central location for application core constants.

Organisation
~~~~~~~~~~~~
Constants are grouped into logical sections with ``# ── Section ──``
headers.  Each group documents its purpose and any associated env-vars.

Boolean env-vars are parsed via the ``_parse_bool_env`` helper so that
``"1"``, ``"true"`` and ``"yes"`` (case-insensitive) are all truthy;
everything else is falsy.

An ``ENV_VAR_REGISTRY`` dict at the bottom of this module catalogues
*every* environment variable read in this file, its default value, and a
short description.  Operators can inspect it programmatically or grep
for a single source of truth.
"""

import os
import tempfile
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────
def _parse_bool_env(var: str, default: str = 'false') -> bool:
    """Return *True* when the env-var *var* is set to a truthy string."""
    return os.getenv(var, default).strip().lower() in ('true', '1', 'yes')


# ── Core Identity & Limits ──────────────────────────────────────────
DEFAULT_AGENT_NAME = 'Orchestrator'
DEFAULT_AGENT_MODE = 'agent'
DEFAULT_MAX_ITERATIONS = (
    10000  # effectively unlimited; circuit breaker handles termination
)

# ── Workspace & Paths ───────────────────────────────────────────────
JWT_SECRET_FILE = '.jwt_secret'
# Default disk root for LocalFileStore when settings do not set ``local_data_root``.
# Uses an absolute user-level directory so Grinta never writes inside the user's workspace.
DEFAULT_LOCAL_DATA_ROOT = '~/.grinta/storage'

DEFAULT_CONFIG_FILE = 'settings.json'

# ── URLs ────────────────────────────────────────────────────────────
# Host:port for the internal MCP HTTP endpoint (same process as default dev API :3000)
DEFAULT_MCP_HOST = 'localhost:3000'

# ── Security ────────────────────────────────────────────────────────
SECRET_PLACEHOLDER = '**********'
# settings.json must not store the real LLM secret; use LLM_API_KEY in .env instead.
LLM_API_KEY_SETTINGS_PLACEHOLDER = '${LLM_API_KEY}'

# ── Cache ───────────────────────────────────────────────────────────
SETTINGS_CACHE_TTL = 60  # seconds

# ── Timeouts & Thresholds ───────────────────────────────────────────
GENERAL_TIMEOUT = 15
# Recall runs KB / vector search synchronously; cap wall time so pending RecallAction always resolves.
RECALL_PIPELINE_TIMEOUT_SECONDS = 90.0
# Max seconds waiting for an observation matching a tool call before timing out.
# 0 or negative = disabled (no timeout error, no watchdog).
DEFAULT_PENDING_ACTION_TIMEOUT = 120.0
# Hard cap on observation handler (``observation_service.handle_observation``)
# wall-clock time.  If the handler hangs (e.g. tool pipeline deadlock, plugin
# hook deadlock), we force-clear pending state and trigger the next step
# instead of letting the agent wedge in RUNNING.  10s is generous for normal
# observation processing but short enough to recover within a single TUI poll.
DEFAULT_OBSERVATION_HANDLER_TIMEOUT_SECONDS = 10.0
# Wall-clock cap on a single step drain iteration.  If a single
# ``_step_inner`` call exceeds this, we force-complete the step task so
# the next iteration can start.  This is a coarse controller backstop for
# non-LLM hangs in action execution, tool pipelines, plugin hooks, etc.;
# LLM streaming liveness is handled by first-chunk/per-chunk timeouts.
DEFAULT_STEP_TASK_LIVENESS_SECONDS = 600.0
# Hard cap on how long run_agent_until_done polls before forcing termination.
# 0 or negative = disabled (no hard cap).  Set
# GRINTA_AGENT_RUN_HARD_TIMEOUT_SECONDS=1800 (or any positive value) to cap
# long sessions when debugging silent stalls.
DEFAULT_AGENT_RUN_HARD_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_AGENT_RUN_HARD_TIMEOUT_SECONDS', '0')
)
# ── Event-loop stall watchdog (backend.core.loop_watchdog) ──────────
# A dedicated OS thread monitors the main asyncio loop for freezes that the
# in-loop timers (liveness ceiling, chunk timeout, observation-handler
# timeout) physically *cannot* catch — a blocked loop cannot fire its own
# timers, so such a freeze leaves no log line and no recovery until it ends.
# When the loop stops ticking for LOOP_WATCHDOG_STALL_SECONDS the watchdog
# dumps every thread's stack so the blocking call names itself.  When the
# watchdog thread *itself* was frozen well past its poll interval, the whole
# process was suspended (OS sleep/hibernate or a long GIL-holding native
# call); that is reported distinctly so frozen time is not mistaken for an
# agent hang.  Set GRINTA_LOOP_WATCHDOG=0 to disable.
LOOP_WATCHDOG_ENABLED = os.getenv('GRINTA_LOOP_WATCHDOG', '1').strip().lower() not in {
    '0',
    'false',
    'no',
    'off',
}
LOOP_WATCHDOG_INTERVAL_SECONDS = float(
    os.getenv('GRINTA_LOOP_WATCHDOG_INTERVAL_SECONDS', '5')
)
LOOP_WATCHDOG_STALL_SECONDS = float(
    os.getenv('GRINTA_LOOP_WATCHDOG_STALL_SECONDS', '60')
)
LOOP_WATCHDOG_SUSPEND_SECONDS = float(
    os.getenv('GRINTA_LOOP_WATCHDOG_SUSPEND_SECONDS', '30')
)
# A single ``run_agent_until_done`` poll sleeps ~0.5s.  If one sleep overruns
# by more than this, the process/loop was frozen (OS sleep/hibernate, or a
# blocking call on the loop thread that the liveness ceiling force-cancels).
# Frozen wall-clock time is *not* the agent failing to make progress, so it is
# credited back to the hard-timeout budget instead of tripping a spurious
# ERROR — the agent resumes as if nothing happened.
DEFAULT_AGENT_RUN_FREEZE_GRACE_SECONDS = float(
    os.getenv('GRINTA_AGENT_RUN_FREEZE_GRACE_SECONDS', '30')
)
# ── LLM HTTP socket timeouts (backend.inference.clients.base) ─────
# Per-request thinking budgets may be large, but connect/read on the wire are
# capped so a dead socket fails fast and hits retry logic instead of wedging
# the agent loop for minutes (Windows TCP give-up ~16m40s).
LLM_HTTP_CONNECT_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_HTTP_CONNECT_TIMEOUT_SECONDS', '10')
)
LLM_HTTP_READ_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_HTTP_READ_TIMEOUT_SECONDS', '30')
)
LLM_HTTP_WRITE_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_HTTP_WRITE_TIMEOUT_SECONDS', '30')
)
LLM_HTTP_POOL_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_HTTP_POOL_TIMEOUT_SECONDS', '10')
)
# Inter-chunk streaming budget: shared by the executor chunk watchdog,
# ``llm.py`` stream iterator, and httpx read timeout for ``astream``.
LLM_STREAM_CHUNK_TIMEOUT_SECONDS = float(
    os.getenv('APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS', '120')
)
# Hard cap on how long the TUI ``_dispatch_to_agent`` poll loop will wait
# without progress before forcing ERROR.  0 = disabled.  Set
# GRINTA_TUI_DISPATCH_TIMEOUT_SECONDS=1800 to re-enable a 30-min stall guard.
DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_TUI_DISPATCH_TIMEOUT_SECONDS', '0')
)
# How long the controller may go with state==RUNNING and no recorded
# ``step()`` call before the no-step-progress watchdog fires.  120s is
# generous enough to absorb a slow LLM streaming response but short enough
# that a genuine stuck-in-RUNNING race surfaces within a couple of minutes.
# Set GRINTA_NO_STEP_PROGRESS_TIMEOUT_SECONDS=0 to disable the watchdog.
DEFAULT_NO_STEP_PROGRESS_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_NO_STEP_PROGRESS_TIMEOUT_SECONDS', '120')
)
# Cooldown between auto-recover attempts by the no-step-progress watchdog.
# After a recovery ``schedule_step_soon`` is issued, the watchdog waits this
# long before declaring a second stall fatal.  Bounds the worst-case stall
# at roughly (timeout + cooldown) seconds.
DEFAULT_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS = float(
    os.getenv('GRINTA_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS', '60')
)
# MCP (stdio/SSE) can exceed the default (npx cold start, slow servers). Pending actions use max(base, this).
MCP_PENDING_ACTION_TIMEOUT_FLOOR = 180.0
# Foreground shell commands (env setup, installs, builds) often run far longer than
# the default pending-action timeout while still progressing normally.
CMD_PENDING_ACTION_TIMEOUT_FLOOR = 600.0
# ``terminal_run`` (session open) must return quickly; long hangs here wedge the
# whole agent step.  ``terminal_input`` / ``terminal_read`` get more headroom.
TERMINAL_RUN_PENDING_ACTION_TIMEOUT_FLOOR = float(
    os.getenv('GRINTA_TERMINAL_RUN_PENDING_TIMEOUT_FLOOR', '60.0')
)
TERMINAL_IO_PENDING_ACTION_TIMEOUT_FLOOR = float(
    os.getenv('GRINTA_TERMINAL_IO_PENDING_TIMEOUT_FLOOR', '120.0')
)
# Legacy alias — highest interactive-terminal pending ceiling.
TERMINAL_PENDING_ACTION_TIMEOUT_FLOOR = TERMINAL_IO_PENDING_ACTION_TIMEOUT_FLOOR
# Hard wall-clock cap on the ``terminal_run`` coroutine (session open path).
TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS', '45.0')
)
# How long to wait for an interactive shell prompt after PTY spawn (pwsh/bash).
PTY_SHELL_READY_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_PTY_SHELL_READY_TIMEOUT_SECONDS', '25.0')
)
# Consecutive empty ``terminal_read`` deltas before auto-closing a ghost session.
TERMINAL_EMPTY_READ_CLOSE_THRESHOLD = int(
    os.getenv('GRINTA_TERMINAL_EMPTY_READ_CLOSE_THRESHOLD', '3')
)
# Interactive PTY: how long the runtime polls the buffer for the *first* byte
# of output after ``open`` / ``input`` before returning an empty result. The
# loop exits as soon as any byte arrives — these caps only matter for slow
# commands (cold PowerShell, npm cold start, etc.). Values are env-tunable
# so operators can tune for slow machines without touching code.
PTY_OPEN_READ_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_PTY_OPEN_READ_TIMEOUT_SECONDS', '2.0')
)
PTY_INPUT_READ_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_PTY_INPUT_READ_TIMEOUT_SECONDS', '1.0')
)
PTY_READ_POLL_INTERVAL_SECONDS = 0.05
# Debugger pending-action floor: DAP step / continue legitimately need more
# than the default 60 s when stepping across slow native code or waiting on
# blocking I/O, but the cmd-run floor (600 s) is far too generous for an
# interactive debugger and was the source of multi-minute "hangs" when an
# adapter wedged. Cap at 120 s so the controller can recover quickly while
# still allowing slow stops / large variable inspections to complete. Operators
# who genuinely need longer can raise it via env override.
DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR = float(
    os.getenv('GRINTA_DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR', '120.0')
)
# Per-tool sync-bridge timeouts. Used by ``call_async_from_sync`` wrappers in
# ``backend/execution/drivers/local/local_runtime_inprocess.py`` so the bridge
# matches the controller's pending-action floor for each ActionType. A small
# buffer is added on top of each tool's own ``action.timeout`` at the call site.
TOOL_BRIDGE_TIMEOUT_FILE_IO = 30.0
TOOL_BRIDGE_TIMEOUT_LSP_QUERY = 30.0
TOOL_BRIDGE_TIMEOUT_DEBUGGER = DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR
TOOL_BRIDGE_TIMEOUT_TERMINAL_RUN = TERMINAL_RUN_PENDING_ACTION_TIMEOUT_FLOOR
TOOL_BRIDGE_TIMEOUT_TERMINAL_IO = TERMINAL_IO_PENDING_ACTION_TIMEOUT_FLOOR
TOOL_BRIDGE_TIMEOUT_BUFFER = 10.0
# Native browser: per-stage fail-fast budgets (see GrintaNativeBrowser).
BROWSER_SESSION_START_TIMEOUT_SEC = 90.0
BROWSER_CDP_NAVIGATE_TIMEOUT_SEC = 20.0
BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC = 45.0
BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC = 40.0
BROWSER_SCREENSHOT_TIMEOUT_SEC = 45.0
# Inline JPEG bytes into LLM context only below this size (vision providers vary).
BROWSER_SCREENSHOT_MAX_INJECT_BYTES = 1_500_000
# Snapshot compaction (interactive / diff modes).
BROWSER_SNAPSHOT_MAX_CHARS_FULL = 120_000
BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE = 12_000
BROWSER_WAIT_TIMEOUT_SEC = 40.0
BROWSER_EXTRACT_TIMEOUT_SEC = 120.0
# Worst single browser_tool call: cold session start + navigate (or snapshot). Not a "hang window".
BROWSER_TOOL_SYNC_TIMEOUT_SECONDS = 300.0

# ── Delegation / Swarming ─────────────────────────────────────────
# Worker timeout: maximum time a delegated worker can run before being terminated.
# Default: 5 minutes (300 seconds). Override via GRINTA_DELEGATE_WORKER_TIMEOUT.
DELEGATE_WORKER_TIMEOUT_SECONDS = float(
    os.getenv('GRINTA_DELEGATE_WORKER_TIMEOUT', '300.0')
)
# Maximum delegation depth: prevents infinite recursion of delegate_task calls.
# Default: 2 (parent → worker → sub-worker). Override via GRINTA_MAX_DELEGATION_DEPTH.
MAX_DELEGATION_DEPTH = int(os.getenv('GRINTA_MAX_DELEGATION_DEPTH', '2'))

# ─ Threshold Constants ─────────────────────────────────────────────
IDLE_RECLAIM_SPIKE_THRESHOLD = 3
EVICTION_SPIKE_THRESHOLD = 1

# ── Runtime Bootstrap ───────────────────────────────────────────────
# Empty prefix: invoke ``python_executable`` directly. Container images may inject a prefix.
DEFAULT_PYTHON_PREFIX: list[str] = []
DEFAULT_MAIN_MODULE = 'backend.execution.server.action_execution_server'

# ── Storage ─────────────────────────────────────────────────────────
# Relative sub-directory under local_data_root for conversation files.
CONVERSATION_BASE_DIR = 'sessions'

# ── Default Configuration ───────────────────────────────────────────
DEFAULT_RUNTIME = 'local'
DEFAULT_FILE_STORE = 'local'


def default_cache_dir() -> str:
    """Return a platform-aware cache directory under the system temp folder."""
    return str(Path(tempfile.gettempdir()) / 'grinta' / 'cache')


DEFAULT_CACHE_DIR = default_cache_dir()
DEFAULT_CONVERSATION_MAX_AGE_SECONDS = 864000
DEFAULT_MAX_CONCURRENT_CONVERSATIONS = 3
DEFAULT_VCS_USER_NAME = 'app'
DEFAULT_VCS_USER_EMAIL = 'grinta@localhost'
DEFAULT_LOG_FORMAT = 'text'
DEFAULT_LOG_LEVEL = 'INFO'
DEFAULT_ENABLE_BROWSER = True
DEFAULT_MAX_BUDGET_PER_TASK = None

# ── Runtime Defaults ────────────────────────────────────────────────
DEFAULT_RUNTIME_TIMEOUT = 900
DEFAULT_RUNTIME_CLOSE_DELAY = 60
DEFAULT_RUNTIME_AUTO_LINT_ENABLED = True
DEFAULT_RUNTIME_KEEP_ALIVE = True

# ── LLM Defaults ────────────────────────────────────────────────────
# No default model until settings.json (llm_model) or env (LLM_MODEL) supplies one.
# Flat settings.json llm_model overrides env when both are set (see load_from_json).
DEFAULT_LLM_MODEL: str | None = None
# Default cap on automatic LLM call retries. The retry decorator (see
# ``backend/inference/retry_mixin.py``) treats this as the *minimum* number
# of attempts: when the most recent failure is a :class:`RateLimitError`
# carrying a server-supplied ``retry_after`` hint, the stop predicate
# extends the budget by ``DEFAULT_LLM_NUM_RETRIES_BONUS_FOR_HINTED`` more
# attempts so the agent honors clearly-bounded provider waits without
# spinning forever on unbounded ones.
DEFAULT_LLM_NUM_RETRIES = 5
DEFAULT_LLM_NUM_RETRIES_BONUS_FOR_HINTED = 5
DEFAULT_LLM_RETRY_MULTIPLIER = 2
DEFAULT_LLM_RETRY_MIN_WAIT = 3
DEFAULT_LLM_RETRY_MAX_WAIT = 30
DEFAULT_LLM_MAX_MESSAGE_CHARS = 15000
DEFAULT_LLM_TEMPERATURE = 0.5
DEFAULT_LLM_TOP_P = 0.95
DEFAULT_LLM_CORRECT_NUM = 5

# ── File Upload ─────────────────────────────────────────────────────
DEFAULT_MAX_FILE_UPLOAD_SIZE_MB = 100
FILES_TO_IGNORE = [
    '.git/',
    '.DS_Store',
    'node_modules/',
    '__pycache__/',
    'lost+found/',
    '.vscode/',
    '.downloads/',
    '.grinta/downloads/',
]

# ── Agent Behavior Defaults ─────────────────────────────────────────
DEFAULT_AGENT_MEMORY_MAX_THREADS = 10
CURRENT_AGENT_CONFIG_SCHEMA_VERSION = '2025-11-14'
DEFAULT_AGENT_MEMORY_ENABLED = True
DEFAULT_AGENT_PROMPT_EXTENSIONS_ENABLED = True
DEFAULT_AGENT_BROWSING_ENABLED = True
DEFAULT_AGENT_WEB_ENABLED = True
DEFAULT_AGENT_DOCS_ENABLED = True
# Vector memory & hybrid retrieval require the optional `[rag]` extra
# (chromadb + bundled ONNX MiniLM). Off by default to keep the base install
# lean (~150 MB vs ~400 MB). Enable via `--rag` CLI flag, agent config, or
# AGENT_VECTOR_MEMORY_ENABLED=1 after running `pip install grinta-ai[rag]`.
DEFAULT_AGENT_VECTOR_MEMORY_ENABLED = False
DEFAULT_AGENT_HYBRID_RETRIEVAL_ENABLED = False
DEFAULT_AGENT_AUTO_LINT_ENABLED = True
DEFAULT_AGENT_AUTO_RETRY_ON_ERROR = True
DEFAULT_AGENT_AUTONOMY_LEVEL = 'balanced'
# DAP / interactive debugger: enabled by default, then runtime-gated by adapter
# detection so the tool appears only when at least one usable adapter is present.
DEFAULT_AGENT_DEBUGGER_ENABLED = True

# Optional LLM-initiated compaction; automatic condensation still runs when needed.
DEFAULT_AGENT_CONDENSATION_REQUEST_ENABLED = False
DEFAULT_AGENT_HISTORY_TRUNCATION_ENABLED = True
DEFAULT_AGENT_PLAN_MODE_ENABLED = True
DEFAULT_AGENT_MCP_ENABLED = True
DEFAULT_AGENT_AUTO_PLANNING_ENABLED = True
DEFAULT_AGENT_PLANNING_COMPLEXITY_THRESHOLD = 3
DEFAULT_AGENT_REFLECTION_ENABLED = True
DEFAULT_AGENT_PLANNING_MIDDLEWARE_ENABLED = True
DEFAULT_AGENT_REFLECTION_MIDDLEWARE_ENABLED = False
DEFAULT_AGENT_REFLECTION_MAX_ATTEMPTS = 2
DEFAULT_AGENT_DYNAMIC_ITERATIONS_ENABLED = True
DEFAULT_AGENT_MIN_ITERATIONS = 50
DEFAULT_AGENT_COMPLEXITY_ITERATION_MULTIPLIER = 50.0
DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS = 300.0
DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY = True
DEFAULT_AGENT_MAX_AUTONOMOUS_ITERATIONS = 0
DEFAULT_AGENT_STUCK_DETECTION_ENABLED = True
DEFAULT_AGENT_STUCK_THRESHOLD_ITERATIONS = 0
# On by default; disable per-deploy via env (AGENT_*) or settings.json agent.* if needed.
DEFAULT_AGENT_TASK_TRACKER_TOOL_ENABLED = True
DEFAULT_AGENT_SOM_VISUAL_BROWSING_ENABLED = True
DEFAULT_AGENT_CLI_MODE = True
DEFAULT_AGENT_ENABLE_FIRST_TURN_ORIENTATION_PROMPT = False
DEFAULT_AGENT_MERGE_CONTROL_SYSTEM_INTO_PRIMARY = False
DEFAULT_APP_MCP_CONFIG_CLS = 'backend.core.config.mcp_config.AppMCPConfig'
DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS = 5
DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS = 10
DEFAULT_AGENT_MAX_STUCK_DETECTIONS = 15
DEFAULT_AGENT_MAX_ERROR_RATE = 0.5
DEFAULT_AGENT_ERROR_RATE_WINDOW = 10
DEFAULT_AGENT_WARNING_FIRST_TRIP_ENABLED = True
DEFAULT_AGENT_WARNING_FIRST_TRIP_LIMIT = 3
DEFAULT_AGENT_PARALLEL_TOOL_SCHEDULING_ENABLED = True

# ── Agent Recovery Heuristics ───────────────────────────────────────
# Threshold knobs for the action-execution repair loop and null-action
# recovery (action_execution_service.py). All counts are inclusive limits.
DEFAULT_AGENT_MAX_CONSECUTIVE_NULL_ACTIONS = 5
# Round 1 injects a directive; round 2+ pauses for user input.
DEFAULT_AGENT_MAX_NULL_RECOVERY_ROUNDS = 2
# Number of LLM repair attempts when get_next_action() raises a recoverable
# parsing/validation error before transitioning to ERROR state.
DEFAULT_AGENT_MAX_REPAIR_ATTEMPTS = 3
# Identical-error escalation: same error N+1 times -> ERROR state.
DEFAULT_AGENT_MAX_IDENTICAL_RETRIES = 2
# Engine-level circuit breaker for ContextLimitError loops. > this -> raise.
DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS = 4
# Engine-level escalation for repeated identical recoverable tool-call errors.
DEFAULT_AGENT_RECOVERABLE_TOOL_ERROR_THRESHOLD = 3
# How many _step_pending requeues SessionOrchestrator._step() will drain.
DEFAULT_AGENT_STEP_DRAIN_LIMIT = 10
# Safe-action parallel batch size cap (parallel reads/searches/thinks).
DEFAULT_AGENT_PARALLEL_BATCH_SIZE = 10

# Hysteresis: when set, record_success() decrements counters by N instead of
# resetting to 0. Keeps memory of past errors so a single housekeeping success
# can't mask a still-failing tool. Set to 0 to restore legacy zero-reset.
DEFAULT_AGENT_ERROR_DECAY_PER_SUCCESS = 1

# ── File Edit Per-Tool Circuit Breaker Thresholds ───────────────────
# Hard (deterministic match/path/guard) failures: switch then pause.
DEFAULT_TEXT_EDITOR_HARD_SWITCH = 2
DEFAULT_TEXT_EDITOR_HARD_PAUSE = 3
# Syntax-validation failures: more generous because models iterate.
DEFAULT_TEXT_EDITOR_SYNTAX_SWITCH = 10
DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE = 15

# ── Stuck Detector Thresholds ───────────────────────────────────────
# Window sizes for fast pattern detection on recent actions/observations.
DEFAULT_STUCK_RECENT_WINDOW = 4
# After detecting stuck, skip re-evaluation for this many agent turns so the
# model has room to act on the recovery directive before being flagged again.
DEFAULT_STUCK_COOLDOWN_TURNS = 3
# A-B-A-B alternating-pattern window (must match in pairs).
# Retained for compute_repetition_score (not used in is_stuck).
DEFAULT_STUCK_AB_PATTERN_WINDOW = 6
# Min consecutive condensation events to declare context-window loop.
DEFAULT_STUCK_CONDENSATION_LOOP_MIN = 10
# Sliding window for semantic loop / cost acceleration analysis.
# Retained for compute_repetition_score (not used in is_stuck).
DEFAULT_STUCK_SEMANTIC_WINDOW = 20
DEFAULT_STUCK_SEMANTIC_MIN_EVENTS = 10
# Intent diversity below this AND failure rate above the next constant trips.
DEFAULT_STUCK_SEMANTIC_DIVERSITY = 0.3
DEFAULT_STUCK_SEMANTIC_FAILURE_RATE = 0.75
# Token-level repetition: 3 identical agent messages above this length trip.
DEFAULT_STUCK_TOKEN_REPETITION_MIN_CHARS = 50
# Cost acceleration: > N tokens added in 5 steps is suspicious.
DEFAULT_STUCK_COST_ACCEL_TOKENS_PER_5_STEPS = 50000
# Absolute prompt-token threshold considered "high context" warning floor.
# NOTE: scaled at runtime against the model's context window when known.
DEFAULT_STUCK_CONTEXT_HIGH_THRESHOLD = 100000
# Continued growth needed alongside high-context to actually trip.
DEFAULT_STUCK_CONTEXT_HIGH_GROWTH = 1000
# Read-only inspection loop: extreme cases only (true degenerate poll loop).
# Stuck-detection recovery: how much one progress signal decrements the
# counter (game-able if too high; ignored if too low).
DEFAULT_STUCK_PROGRESS_SIGNAL_DECREMENT = 2

# ── Knowledge Base Defaults ─────────────────────────────────────────
DEFAULT_KB_ENABLED = True
DEFAULT_KB_ACTIVE_COLLECTION_IDS: list[str] = []
DEFAULT_KB_SEARCH_TOP_K = 5
DEFAULT_KB_RELEVANCE_THRESHOLD = 0.7
DEFAULT_KB_AUTO_SEARCH = True
DEFAULT_KB_SEARCH_STRATEGY = 'hybrid'

# ── API & Server ────────────────────────────────────────────────────
API_VERSION_V1 = 'v1'
CURRENT_API_VERSION = API_VERSION_V1

# API versioning is strict by default: unversioned /api/ requests are
# rejected with a 400 suggesting the correct path.  Existing deployments
# that rely on unversioned routes can set APP_PERMISSIVE_API=1 to
# restore the old permissive behavior during migration.
ENFORCE_API_VERSIONING = os.getenv('APP_PERMISSIVE_API', '').strip().lower() not in (
    '1',
    'true',
    'yes',
)

# ── Logging & Debug (env-var driven) ────────────────────────────────
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
DEBUG = _parse_bool_env('DEBUG')
DEBUG_LLM = _parse_bool_env('DEBUG_LLM', default='false')
LOG_JSON = _parse_bool_env('LOG_JSON', default='true')  # Default to JSON for production
LOG_JSON_LEVEL_KEY = os.getenv('LOG_JSON_LEVEL_KEY', 'level')
# Enable OTEL log correlation when explicitly requested, defaulting to OTEL_ENABLED
OTEL_LOG_CORRELATION = _parse_bool_env(
    'OTEL_LOG_CORRELATION',
    default=os.getenv('OTEL_ENABLED', 'false'),
)
LOG_TO_FILE = _parse_bool_env('LOG_TO_FILE', default='true')
LOG_ALL_EVENTS = _parse_bool_env('LOG_ALL_EVENTS')
APP_DEBUG_PROMPT_ROLES = _parse_bool_env('APP_DEBUG_PROMPT_ROLES', default='true')
APP_DEBUG_REASONING_ASTEP = _parse_bool_env(
    'APP_DEBUG_REASONING_ASTEP', default='false'
)
APP_DEBUG_MODE = _parse_bool_env('APP_DEBUG_MODE', default='true')

LOG_COLORS = {
    'ACTION': 'green',
    'USER_ACTION': 'light_red',
    'OBSERVATION': 'yellow',
    'USER_OBSERVATION': 'light_green',
    'DETAIL': 'cyan',
    'ERROR': 'red',
    'PLAN': 'light_magenta',
}

DISABLE_COLOR_PRINTING = False

# ── Security Risk ───────────────────────────────────────────────────
SECURITY_RISK_DESC = (
    "Required. Your assessment of this action's safety risk (LOW/MEDIUM/HIGH). "
    'Server may only escalate (e.g. true-unsafe commands always become HIGH); '
    'it never silently lowers your label or invents one when omitted. '
    'See the SECURITY_RISK_ASSESSMENT section in the system prompt for definitions.'
)
RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH']

# ── UX / Error Presentation ─────────────────────────────────────────
# ErrorSeverity, ErrorCategory enums live in backend.core.enums

# ── Command Output ──────────────────────────────────────────────────
CMD_OUTPUT_PS1_BEGIN = '\n###PS1JSON###\n'
CMD_OUTPUT_PS1_END = '\n###PS1END###'
MAX_CMD_OUTPUT_SIZE = 10000
DEFAULT_CMD_EXIT_CODE = -1
DEFAULT_CMD_PID = -1

# ── Runtime Messages ────────────────────────────────────────────────
# Runtime constants
BASH_TIMEOUT_MESSAGE_TEMPLATE = (
    "You may wait longer to see additional output by sending empty command '', "
    'send other commands to interact with the current process, '
    'send keys ("C-c", "C-z", "C-d") to interrupt/kill the previous command '
    'before sending your new command, or use the timeout parameter in the active terminal tool '
    '(execute_bash or execute_powershell, depending on runtime) '
    'for future commands.'
)

# ── Compactor Defaults ──────────────────────────────────────────────
DEFAULT_COMPACTOR_ATTENTION_WINDOW = 100
DEFAULT_COMPACTOR_KEEP_FIRST = 1
DEFAULT_COMPACTOR_MAX_EVENTS = 300
DEFAULT_COMPACTOR_MAX_SIZE = 300
DEFAULT_COMPACTOR_MAX_EVENT_LENGTH = 10000
DEFAULT_SMART_COMPACTOR_MAX_SIZE = 600
DEFAULT_SMART_COMPACTOR_KEEP_FIRST = 5
DEFAULT_SMART_COMPACTOR_IMPORTANCE_THRESHOLD = 0.6
DEFAULT_SMART_COMPACTOR_RECENCY_BONUS_WINDOW = 20

# ── Tool Result Persistence (context pressure relief) ───────────────
DEFAULT_TOOL_RESULT_PERSIST_THRESHOLD_CHARS = 12_000
DEFAULT_TOOL_RESULTS_PER_MESSAGE_CHARS = 80_000
DEFAULT_TOOL_RESULT_PREVIEW_CHARS = 2_000

# ── Prompt Window Floors (coding-agent continuity) ──────────────────
DEFAULT_PROMPT_MIN_TOOL_LOOPS = 12
DEFAULT_PROMPT_MIN_TAIL_TOKENS = 8_000
DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET = 4_000

# ── Compaction Boundary / Proactive Threshold ───────────────────────
DEFAULT_COMPACTION_RESERVED_SUMMARY_TOKENS = 13_000
DEFAULT_MICROCOMPACT_PRESERVE_RECENT = 80
DEFAULT_CONTINUITY_GATE_MIN_SCORE = 0.6

# ── Unified Context Pipeline ────────────────────────────────────────
DEFAULT_SESSION_MEMORY_INIT_TOKENS = 10_000
DEFAULT_SESSION_MEMORY_UPDATE_TOKENS = 5_000
DEFAULT_SESSION_MEMORY_UPDATE_TOOL_CALLS = 3
DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS = 300
DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS = 60
DEFAULT_COMPACT_MIN_PRUNED_EVENTS = 20
DEFAULT_COMPACT_MIN_TOKEN_REDUCTION = 10_000
# After ineffective compaction, skip retries until N new events land (and time backoff).
DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS = 30
DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS = 120
DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS = 90
# 5c tail target: fraction of autocompact threshold to keep post-prune.
DEFAULT_DEGRADED_COMPACT_TAIL_RATIO = 0.55
DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS = 15
DEFAULT_POST_COMPACT_TOKEN_BUDGET = 6_000
DEFAULT_POST_COMPACT_MAX_FILES = 2
DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS = 1_500

# ── Session Log Audit ───────────────────────────────────────────────
DEFAULT_SESSION_AUDIT_REFRESH_SECONDS = 120

# ── Permissions & Safety Defaults ───────────────────────────────────
DEFAULT_FILE_OPERATIONS_MAX_SIZE_MB = 50
DEFAULT_FILE_OPERATIONS_BLOCKED_PATHS = [
    '/etc/**',  # System config
    '/sys/**',  # System files
    '/proc/**',  # Process info
    '~/.ssh/**',  # SSH keys
    '**/.env',  # Environment files with secrets
    '**/id_rsa*',  # Private keys
    '**/id_ed25519*',  # Private keys
]
DEFAULT_GIT_PROTECTED_BRANCHES = ['main', 'master', 'production', 'prod']
DEFAULT_NETWORK_MAX_REQUESTS_PER_MINUTE = 60
DEFAULT_PACKAGE_ALLOWED_MANAGERS = ['pip', 'npm', 'yarn', 'pnpm', 'uv', 'cargo', 'bun']
DEFAULT_SHELL_BLOCKED_COMMANDS = [
    'rm -rf /',
    'mkfs',
    'dd',
    'fork',
    ':(){ :|:& };:',  # Fork bomb
]
DEFAULT_SHELL_CONFIRMATION_PATTERNS = [
    r'rm\s+-rf',
    r'sudo\s+',
    r'chmod\s+',
    r'chown\s+',
]
DEFAULT_BROWSER_MAX_PAGES = 10

# ── Runtime Resource Limits ─────────────────────────────────────────
DEFAULT_RUNTIME_MAX_MEMORY_MB = 2048
DEFAULT_RUNTIME_MAX_CPU_PERCENT = 80.0
DEFAULT_RUNTIME_MAX_DISK_GB = 10
DEFAULT_RUNTIME_MAX_FILE_COUNT = 10000
DEFAULT_RUNTIME_MAX_NETWORK_REQUESTS_PER_MINUTE = 100
MAX_FILENAME_LENGTH = 255
MAX_PATH_LENGTH = 4096  # Maximum path length (POSIX limit)
MAX_FILE_SIZE_FOR_GIT_DIFF = 1024 * 1024

# ── MCP Client ──────────────────────────────────────────────────────
DEFAULT_MCP_CACHE_TTL_SECONDS = 600
MAX_MCP_CACHE_ENTRY_BYTES = 5 * 1024 * 1024
MCP_CACHEABLE_TOOLS = {
    'list_components',
    'list_blocks',
    'get_component',
    'get_block',
    'get_component_metadata',
}

# ── Whitespace Handling ─────────────────────────────────────────────
DEFAULT_INDENT_SIZES = {
    'python': 4,
    'javascript': 2,
    'typescript': 2,
    'tsx': 2,
    'go': 1,  # Go uses tabs
    'rust': 4,
    'java': 4,
    'c': 4,
    'cpp': 4,
    'c_sharp': 4,
    'ruby': 2,
    'php': 4,
    'swift': 4,
    'kotlin': 4,
    'scala': 2,
    'json': 2,
    'yaml': 2,
    'html': 2,
    'css': 2,
}

# ── Storage Defaults ────────────────────────────────────────────────
DEFAULT_SECRETS_FILENAME = 'user_secrets.json'


# ── Env-Var Registry ───────────────────────────────────────────────
# Single source of truth for every environment variable read in this
# module.  Format:  "VAR_NAME": ("default", "description")
# Operators can inspect this dict or ``grep ENV_VAR_REGISTRY`` to
# discover every knob.
ENV_VAR_REGISTRY: dict[str, tuple[str, str]] = {
    # Logging & debug
    'LOG_LEVEL': ('INFO', 'Root log level (DEBUG / INFO / WARNING / ERROR)'),
    'DEBUG': ('false', 'Enable general debug mode'),
    'DEBUG_LLM': ('false', 'Log raw LLM request/response payloads'),
    'APP_CLI_SHOW_REASONING_TEXT': (
        'true',
        'Render reasoning/thinking text in CLI panels; set false/0 to suppress provider reasoning leakage',
    ),
    'LOG_JSON': ('true', 'Emit structured JSON logs (recommended for prod)'),
    'LOG_JSON_LEVEL_KEY': ('level', 'JSON key name for the log-level field'),
    'OTEL_LOG_CORRELATION': ('<OTEL_ENABLED>', 'Attach OTEL trace/span IDs to logs'),
    'OTEL_ENABLED': ('false', 'Master switch for OpenTelemetry integration'),
    'LOG_TO_FILE': (
        'true',
        'Append structured logs under repo logs/app.log; set LOG_TO_FILE=false to disable — when off the CLI keeps the app logger at ERROR on the console',
    ),
    'LOG_ALL_EVENTS': ('True', 'Log every event processed by the event stream'),
    'APP_DEBUG_PROMPT_ROLES': (
        'true',
        'Per astep: log message role histogram after build_messages (condensed event count, '
        'pending condensation, assistant tool-call presence); set false to disable; use with '
        'LOG_LEVEL=INFO or DEBUG',
    ),
    'APP_DEBUG_REASONING_ASTEP': (
        'false',
        'CLI: log ReasoningDisplay lifecycle/thought/action updates with shared astep_id '
        '(see APP_DEBUG_PROMPT_ROLES) to correlate UI with LLM steps',
    ),
    'APP_DEBUG_MODE': (
        'true',
        'Log planner/executor mode and toolset details at INFO; set false to disable',
    ),
    'GRINTA_DEBUGGER_SYNC_POOL_WORKERS': (
        '6',
        'Thread cap for dedicated DebuggerAction sync pool (isolated from general bridge EXECUTOR)',
    ),
    'GRINTA_AGENT_RUN_HARD_TIMEOUT_SECONDS': (
        '0',
        'Hard cap (seconds) for run_agent_until_done polling; 0 disables the cap entirely '
        'so long sessions are never forcibly terminated.',
    ),
    'APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS': (
        '120',
        'Max seconds between streamed LLM chunks before timeout; also sets httpx read '
        'timeout for streaming and the executor chunk watchdog',
    ),
    # API versioning
    'APP_PERMISSIVE_API': (
        '',
        "Set to '1' to allow unversioned /api/ routes (deprecated)",
    ),
}

# All enum classes (ContentType, ActionType, AgentState, ObservationType,
# ExitReason, ActionConfirmationStatus, ActionSecurityRisk, AppMode,
# EventVersion, EventSource, FileEditSource, FileReadSource, RecallType,
# RetryStrategy, RuntimeStatus) are defined in backend.core.enums.
