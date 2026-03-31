"""State models and helpers for tracking agent conversations."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, SupportsIndex

import backend
from backend.orchestration.state.control_flags import (
    BudgetControlFlag,
    IterationControlFlag,
)
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import PlaybookFinishAction
from backend.ledger.event import Event, EventSource
from backend.inference.metrics import Metrics
from backend.context.view import View
from backend.persistence.locations import get_conversation_agent_state_filename

if TYPE_CHECKING:
    from backend.gateway.services.conversation_stats import ConversationStats
    from backend.persistence.files import FileStore

RESUMABLE_STATES = [
    AgentState.RUNNING,
    AgentState.PAUSED,
    AgentState.AWAITING_USER_INPUT,
    AgentState.FINISHED,
]

# Versioned JSON format — bump when schema changes
STATE_SCHEMA_VERSION = 2

# Number of timestamped state checkpoints to retain for crash recovery.
# On restore, if the primary file is corrupt we try checkpoints newest-first.
MAX_STATE_CHECKPOINTS = 3


def _serialize_metrics_like(obj: Any) -> Any:
    """Serialize metrics or parent_metrics_snapshot to dict."""
    return obj.get() if obj is not None and hasattr(obj, "get") else None


def _serialize_state_scalars(data: dict) -> dict[str, Any]:
    """Extract scalar and enum fields into doc."""
    doc: dict[str, Any] = {"_schema_version": STATE_SCHEMA_VERSION}
    for key in (
        "session_id", "user_id", "confirmation_mode", "delegate_level",
        "start_id", "end_id", "parent_iteration", "last_error",
    ):
        if key in data:
            doc[key] = data[key]
    for key in ("agent_state", "resume_state"):
        val = data.get(key)
        doc[key] = val.value if isinstance(val, Enum) else val
    for key in ("inputs", "outputs", "extra_data"):
        doc[key] = data.get(key, {})
    return doc


def _serialize_state_typed_fields(data: dict) -> dict[str, Any]:
    """Extract dataclass/dataclass-like and metrics fields."""
    doc: dict[str, Any] = {}
    ts = data.get("turn_signals")
    doc["turn_signals"] = asdict(ts) if ts else None
    for key in ("iteration_flag", "budget_flag"):
        flag = data.get(key)
        doc[key] = asdict(flag) if flag else None
    doc["metrics"] = _serialize_metrics_like(data.get("metrics"))
    doc["parent_metrics_snapshot"] = _serialize_metrics_like(data.get("parent_metrics_snapshot"))
    plan = data.get("plan")
    doc["plan"] = asdict(plan) if plan and hasattr(plan, "steps") else None
    return doc


def _build_state_serialization_doc(data: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-serializable dict from state __getstate__ data."""
    doc = _serialize_state_scalars(data)
    doc.update(_serialize_state_typed_fields(data))
    return doc


def _apply_state_scalars(state: State, doc: dict) -> None:
    """Apply simple scalar fields from doc to state."""
    scalar_keys = (
        "session_id", "user_id", "confirmation_mode", "delegate_level",
        "start_id", "end_id", "parent_iteration", "last_error",
    )
    for key in scalar_keys:
        if key in doc:
            setattr(state, key, doc[key])


def _apply_state_enums_and_dicts(state: State, doc: dict) -> None:
    """Apply enum and dict fields from doc to state."""
    agent_state_val = doc.get("agent_state")
    if agent_state_val is not None:
        state.set_agent_state(AgentState(agent_state_val), source="State._from_json_str")
    r = doc.get("resume_state")
    state.resume_state = AgentState(r) if r else None
    state.inputs = doc.get("inputs", {})
    state.outputs = doc.get("outputs", {})
    state.extra_data = doc.get("extra_data", {})


def _apply_state_turn_signals(state: State, doc: dict) -> None:
    """Apply turn_signals from doc to state."""
    ts = doc.get("turn_signals")
    if isinstance(ts, dict):
        state.turn_signals = TurnSignals(
            planning_directive=ts.get("planning_directive"),
            memory_pressure=ts.get("memory_pressure"),
            repetition_score=float(ts.get("repetition_score", 0.0) or 0.0),
        )


def _apply_state_control_flags(state: State, doc: dict) -> None:
    """Apply iteration_flag and budget_flag from doc to state."""
    iflag = doc.get("iteration_flag")
    if isinstance(iflag, dict):
        state.iteration_flag = IterationControlFlag(
            limit_increase_amount=iflag.get("limit_increase_amount", 100),
            current_value=iflag.get("current_value", 0),
            max_value=iflag.get("max_value", 100),
            headless_mode=iflag.get("headless_mode", False),
        )
    bflag = doc.get("budget_flag")
    if isinstance(bflag, dict):
        state.budget_flag = BudgetControlFlag(
            limit_increase_amount=bflag.get("limit_increase_amount", 0.0),
            current_value=bflag.get("current_value", 0.0),
            max_value=bflag.get("max_value", 0.0),
            headless_mode=bflag.get("headless_mode", False),
        )


def _apply_state_metrics(state: State, doc: dict) -> None:
    """Apply metrics and parent_metrics_snapshot from doc to state."""
    for key, attr in [("metrics", "metrics"), ("parent_metrics_snapshot", "parent_metrics_snapshot")]:
        d = doc.get(key)
        if isinstance(d, dict):
            m = Metrics()
            m.__setstate__(d)
            setattr(state, attr, m)


VALID_PLAN_STEP_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "failed", "skipped"}
)


def _normalize_plan_step_status(raw_status: Any) -> str:
    status = str(raw_status or "pending").strip().lower()
    return status if status in VALID_PLAN_STEP_STATUSES else "pending"


def normalize_plan_step_payload(step: Any, idx: int | None = None) -> dict[str, Any]:
    """Normalize plan/task-tracker step payloads to the canonical schema."""
    if not isinstance(step, dict):
        msg = f"Plan step must be a dictionary, got {type(step)}"
        raise TypeError(msg)

    fallback_id = f"step-{idx}" if idx is not None else "step"
    subtasks = step.get("subtasks", [])
    if subtasks is None:
        subtasks = []
    if not isinstance(subtasks, list):
        msg = "Plan step 'subtasks' must be a list"
        raise TypeError(msg)

    tags = step.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        msg = "Plan step 'tags' must be a list"
        raise TypeError(msg)

    return {
        "id": str(step.get("id") or fallback_id),
        "description": str(step.get("description") or step.get("title") or "Untitled step"),
        "status": _normalize_plan_step_status(step.get("status")),
        "result": step.get("result", step.get("notes")),
        "tags": [str(tag) for tag in tags],
        "subtasks": [
            normalize_plan_step_payload(substep, i + 1)
            for i, substep in enumerate(subtasks)
        ],
    }


def build_plan_step_from_payload(step: dict[str, Any], idx: int | None = None) -> PlanStep:
    """Build a ``PlanStep`` from normalized-or-legacy payload data."""
    normalized = normalize_plan_step_payload(step, idx)
    return PlanStep(
        id=normalized["id"],
        description=normalized["description"],
        status=normalized["status"],
        result=normalized["result"],
        subtasks=[
            build_plan_step_from_payload(substep, i + 1)
            for i, substep in enumerate(normalized["subtasks"])
        ],
        tags=normalized["tags"],
    )


def build_active_plan_from_payload(
    raw_steps: list[dict[str, Any]],
    *,
    title: str = "Current Plan",
) -> ActivePlan:
    """Build an ``ActivePlan`` from external payload data."""
    return ActivePlan(
        steps=[
            build_plan_step_from_payload(step, i + 1)
            for i, step in enumerate(raw_steps)
        ],
        title=title,
    )


def _apply_state_plan(state: State, doc: dict) -> None:
    """Apply plan from doc to state."""
    plan_dict = doc.get("plan")
    if not isinstance(plan_dict, dict):
        return
    try:
        raw_steps = plan_dict.get("steps", [])
        if not isinstance(raw_steps, list):
            raise TypeError("Plan 'steps' must be a list")
        state.plan = build_active_plan_from_payload(
            raw_steps,
            title=plan_dict.get("title", "Current Plan"),
        )
    except Exception as e:
        logger.warning("Failed to restore plan from state: %s", e)


@dataclass
class TurnSignals:
    """First-class, turn-scoped control signals for agents.

    These signals are meant to be:
    - deterministic (typed vs. ad-hoc extra_data)
    - retry-safe (consumed via explicit acknowledgements)
    - optionally surfaced to the LLM in a dedicated control message
    """

    planning_directive: str | None = None
    memory_pressure: str | None = None
    repetition_score: float = 0.0


@dataclass
class PlanStep:
    """A single step in the agent's active plan."""

    id: str
    description: str
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    result: str | None = None
    subtasks: list[PlanStep] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ActivePlan:
    """The agent's current active plan."""

    steps: list[PlanStep] = field(default_factory=list)
    title: str = "Current Plan"

    def find_step(self, step_id: str) -> PlanStep | None:
        """Find a step by ID recursively."""
        for step in self.steps:
            if step.id == step_id:
                return step
            found = self._find_in_subtasks(step, step_id)
            if found:
                return found
        return None

    def _find_in_subtasks(self, parent: PlanStep, step_id: str) -> PlanStep | None:
        for step in parent.subtasks:
            if step.id == step_id:
                return step
            found = self._find_in_subtasks(step, step_id)
            if found:
                return found
        return None


@dataclass(frozen=True)
class RestoreProvenance:
    """Describe how a persisted State object was restored."""

    source: str
    path: str
    primary_error: str | None = None


class TrafficControlState:
    """Track pause/resume state for agent loops and manage iteration counters."""

    NORMAL = "normal"
    THROTTLING = "throttling"
    PAUSED = "paused"


class TrackedHistoryList(list):
    """List wrapper that bumps State history version on in-place mutation."""

    def __init__(self, owner: State | None = None, values: list[Any] | None = None):
        super().__init__(values or [])
        self.owner = owner

    def attach_owner(self, owner: State) -> None:
        self.owner = owner

    def _mark(self) -> None:
        owner = self.owner
        if owner is not None:
            owner.mark_history_mutated()

    def append(self, item: Any) -> None:
        super().append(item)
        self._mark()

    def extend(self, iterable) -> None:
        super().extend(iterable)
        self._mark()

    def insert(self, index: SupportsIndex, item: Any) -> None:
        super().insert(index, item)
        self._mark()

    def clear(self) -> None:
        super().clear()
        self._mark()

    def pop(self, index: SupportsIndex = -1):
        result = super().pop(index)
        self._mark()
        return result

    def remove(self, value: Any) -> None:
        super().remove(value)
        self._mark()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        super().sort(*args, **kwargs)
        self._mark()

    def reverse(self) -> None:
        super().reverse()
        self._mark()

    def __setitem__(self, index, value) -> None:
        super().__setitem__(index, value)
        self._mark()

    def __delitem__(self, index) -> None:
        super().__delitem__(index)
        self._mark()


@dataclass
class State:
    """Represents the running state of an agent in the App system, saving data of its operation and memory.

    - Multi-agent/delegate state:
      - store the task (conversation between the agent and the user)
      - the subtask (conversation between an agent and the user or another agent)
      - global and local iterations
      - delegate levels for multi-agent interactions
      - almost stuck state

    - Running state of an agent:
      - current agent state (e.g., LOADING, RUNNING, PAUSED)
      - traffic control state for rate limiting
      - confirmation mode
      - the last error encountered

    - Data for saving and restoring the agent:
      - save to and restore from a session
      - serialize with pickle and base64

    - Save / restore data about message history
      - start and end IDs for events in agent's history
      - summaries and delegate summaries

    - Metrics:
      - global metrics for the current task
      - local metrics for the current subtask

    - Extra data:
      - additional task-specific data
    """

    session_id: str = ""
    user_id: str | None = None
    iteration_flag: IterationControlFlag = field(
        default_factory=lambda: IterationControlFlag(
            limit_increase_amount=100,
            current_value=0,
            max_value=100,
        ),
    )
    conversation_stats: ConversationStats | None = None
    budget_flag: BudgetControlFlag | None = None
    confirmation_mode: bool = False
    history: list[Event] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    agent_state: AgentState = AgentState.LOADING
    resume_state: AgentState | None = None
    delegate_level: int = 0
    start_id: int = -1
    end_id: int = -1
    parent_metrics_snapshot: Metrics | None = None
    parent_iteration: int = 100
    extra_data: dict[str, Any] = field(default_factory=dict)
    turn_signals: TurnSignals = field(default_factory=TurnSignals)
    last_error: str = ""
    iteration: int | None = None
    local_iteration: int | None = None
    max_iterations: int | None = None
    traffic_control_state: TrafficControlState | None = None
    local_metrics: Metrics | None = None
    delegates: dict[tuple[int, int], tuple[str, str]] | None = None
    metrics: Metrics = field(default_factory=Metrics)
    plan: ActivePlan | None = None
    restore_provenance: RestoreProvenance | None = None

    def __post_init__(self) -> None:
        self._history_version = 0
        self._view_history_version = -1
        self._view = View.from_events([])
        self.history = self.history

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "history":
            wrapped = self._coerce_history(value)
            super().__setattr__(name, wrapped)
            self.mark_history_mutated()
            return
        super().__setattr__(name, value)

    def _coerce_history(self, value: Any) -> TrackedHistoryList:
        if isinstance(value, TrackedHistoryList):
            value.attach_owner(self)
            return value
        return TrackedHistoryList(self, list(value or []))

    def mark_history_mutated(self) -> None:
        current = getattr(self, "_history_version", 0)
        self._history_version = current + 1
        self._cached_first_user_message = None

    def set_restore_provenance(
        self,
        source: str,
        path: str,
        *,
        primary_error: str | None = None,
    ) -> None:
        """Record where restored state came from for logging and diagnostics."""
        self.restore_provenance = RestoreProvenance(
            source=source,
            path=path,
            primary_error=primary_error,
        )

    # ------------------------------------------------------------------ #
    # Centralized mutation methods
    # ------------------------------------------------------------------ #
    # These provide a single write-path per mutable concern, making it
    # easy to add logging, validation, or change-tracking later without
    # hunting through 6+ services for direct field assignments.

    def set_last_error(self, message: str, *, source: str = "") -> None:
        """Set the last error message with optional origin tag for debuggability."""
        self.last_error = message
        if message and source:
            logger.debug("State.last_error set by %s: %s", source, message[:120])

    def set_outputs(self, outputs: dict, *, source: str = "") -> None:
        """Set the task outputs dict."""
        self.outputs = outputs
        if source:
            logger.debug("State.outputs set by %s (%d keys)", source, len(outputs))

    def set_extra(self, key: str, value: Any, *, source: str = "") -> None:
        """Set a single key in the extra_data bag."""
        self.extra_data[key] = value
        if source:
            logger.debug("State.extra_data[%s] set by %s", key, source)

    def set_planning_directive(self, directive: str, *, source: str = "") -> None:
        """Set the current planning directive for the next LLM turn."""
        self.turn_signals.planning_directive = directive
        if source:
            logger.debug("State.turn_signals.planning_directive set by %s", source)

    def ack_planning_directive(self, *, source: str = "") -> None:
        """Acknowledge/clear the current planning directive after success."""
        if self.turn_signals.planning_directive is None:
            return
        self.turn_signals.planning_directive = None
        if source:
            logger.debug("State.turn_signals.planning_directive acked by %s", source)

    def set_memory_pressure(self, level: str, *, source: str = "") -> None:
        """Set a memory-pressure signal for the next turn."""
        self.turn_signals.memory_pressure = level
        if source:
            logger.debug("State.turn_signals.memory_pressure set by %s", source)

    def ack_memory_pressure(self, *, source: str = "") -> None:
        """Acknowledge/clear memory pressure after it has been handled."""
        if self.turn_signals.memory_pressure is None:
            return
        self.turn_signals.memory_pressure = None
        if source:
            logger.debug("State.turn_signals.memory_pressure acked by %s", source)

    def adjust_iteration_limit(self, new_max: int, *, source: str = "") -> None:
        """Safely adjust the iteration flag's max_value."""
        if self.iteration_flag is not None:
            old = getattr(self.iteration_flag, "max_value", None)
            self.iteration_flag.max_value = new_max
            if source:
                logger.debug(
                    "State.iteration_flag.max_value %s→%s by %s", old, new_max, source
                )

    def set_agent_state(self, new_state: AgentState, *, source: str = "") -> None:
        """Set agent_state through a single validated mutation path."""
        old_state = self.agent_state
        self.agent_state = new_state
        if source and old_state != new_state:
            logger.debug("State.agent_state %s→%s by %s", old_state, new_state, source)

    def save_to_session(
        self,
        sid: str,
        file_store: FileStore,
        user_id: str | None,
    ) -> None:
        """Save agent state to persistent storage as versioned JSON.

        Also writes a timestamped checkpoint copy, keeping the last
        ``MAX_STATE_CHECKPOINTS`` versions.  On restore, if the primary
        file is corrupt we fall back to the newest valid checkpoint.

        Falls back to pickle/base64 only if JSON serialization fails unexpectedly.

        Args:
            sid: Session ID
            file_store: File storage backend
            user_id: Optional user ID for scoping

        """
        conversation_stats = self.conversation_stats
        self.conversation_stats = None
        try:
            encoded = self._to_json_str()
        except Exception:
            logger.exception(
                "JSON serialization of agent state failed for sid %s — "
                "this is a bug; investigate which field is not JSON-safe",
                sid,
            )
            raise
        logger.debug("Saving state to session %s:%s", sid, self.agent_state)
        try:
            primary = get_conversation_agent_state_filename(sid, user_id)
            file_store.write(primary, encoded)

            # Write a timestamped checkpoint and prune old ones
            self._write_checkpoint(file_store, sid, user_id, encoded)

            if user_id:
                filename = get_conversation_agent_state_filename(sid)
                try:
                    file_store.delete(filename)
                except Exception:
                    logger.debug("Failed to delete legacy state file %s", filename)
        except Exception as e:
            logger.error("Failed to save state to session: %s", e)
            raise
        finally:
            self.conversation_stats = conversation_stats

    @staticmethod
    def _checkpoint_dir(sid: str, user_id: str | None) -> str:
        """Return the directory path for state checkpoints."""
        from backend.persistence.locations import get_conversation_dir

        return f"{get_conversation_dir(sid, user_id)}state_checkpoints/"

    @staticmethod
    def _write_checkpoint(
        file_store: FileStore,
        sid: str,
        user_id: str | None,
        encoded: str,
    ) -> None:
        """Write a timestamped state checkpoint and prune old ones."""
        ckpt_dir = State._checkpoint_dir(sid, user_id)
        ts = int(time.time() * 1000)
        ckpt_file = f"{ckpt_dir}{ts}.json"
        try:
            file_store.write(ckpt_file, encoded)
        except Exception:
            logger.debug("Failed to write state checkpoint %s", ckpt_file)
            return

        # Prune — keep only the newest MAX_STATE_CHECKPOINTS files
        try:
            files = file_store.list(ckpt_dir)
            # Filter to .json files and sort by name (timestamp) descending
            json_files = sorted(
                [f for f in files if f.endswith(".json")],
                reverse=True,
            )
            for old_file in json_files[MAX_STATE_CHECKPOINTS:]:
                try:
                    file_store.delete(f"{ckpt_dir}{old_file}")
                except Exception:
                    logger.debug("Failed to prune old checkpoint %s", old_file)
        except Exception:
            # list() may fail if directory doesn't exist yet — that's fine
            logger.debug(
                "Could not list checkpoint dir %s (may not exist yet)", ckpt_dir
            )

    @staticmethod
    def restore_from_session(
        sid: str,
        file_store: FileStore,
        user_id: str | None = None,
    ) -> State:
        """Restore state from session, supporting both JSON (v1+) and legacy pickle.

        If the primary state file is corrupt, falls back to the newest
        valid checkpoint (up to ``MAX_STATE_CHECKPOINTS`` are kept).
        """
        state: State | None = None
        primary_error: Exception | None = None
        restore_path = get_conversation_agent_state_filename(sid, user_id)

        # --- Try the primary file first ---
        try:
            raw = file_store.read(
                restore_path,
            )
        except FileNotFoundError as e:
            if not user_id:
                # Before giving up, try checkpoints
                state = State._restore_from_checkpoints(
                    file_store,
                    sid,
                    user_id,
                    primary_error=e,
                )
                if state is not None:
                    return state
                msg = f"Could not restore state from session file for sid: {sid}"
                raise FileNotFoundError(msg) from e
            filename = get_conversation_agent_state_filename(sid)
            restore_path = filename
            try:
                raw = file_store.read(filename)
            except FileNotFoundError:
                state = State._restore_from_checkpoints(
                    file_store,
                    sid,
                    user_id,
                    primary_error=e,
                )
                if state is not None:
                    return state
                raise

        try:
            state = State._from_raw(raw)
        except Exception as e:
            primary_error = e
            logger.warning(
                "Primary state file corrupt for sid %s, trying checkpoints: %s",
                sid,
                e,
            )
            state = State._restore_from_checkpoints(
                file_store,
                sid,
                user_id,
                primary_error=e,
            )
            if state is None:
                raise primary_error from e

        state.set_restore_provenance(
            "primary",
            restore_path,
            primary_error=str(primary_error) if primary_error else None,
        )

        if state.agent_state in RESUMABLE_STATES:
            state.resume_state = state.agent_state
        else:
            state.resume_state = None
        state.set_agent_state(AgentState.LOADING, source="State.restore_from_session")
        return state

    @staticmethod
    def _restore_from_checkpoints(
        file_store: FileStore,
        sid: str,
        user_id: str | None,
        *,
        primary_error: Exception | None = None,
    ) -> State | None:
        """Try restoring from checkpoint files, newest first.

        Returns:
            A valid State if any checkpoint was successfully parsed, else None.
        """
        ckpt_dir = State._checkpoint_dir(sid, user_id)
        try:
            files = file_store.list(ckpt_dir)
        except Exception:
            return None

        json_files = sorted(
            [f for f in files if f.endswith(".json")],
            reverse=True,
        )
        for ckpt_name in json_files[:MAX_STATE_CHECKPOINTS]:
            try:
                ckpt_path = f"{ckpt_dir}{ckpt_name}"
                raw = file_store.read(ckpt_path)
                state = State._from_raw(raw)
                state.set_restore_provenance(
                    "checkpoint",
                    ckpt_path,
                    primary_error=str(primary_error) if primary_error else None,
                )
                logger.info(
                    "Restored state from checkpoint %s for sid %s",
                    ckpt_name,
                    sid,
                )
                return state
            except Exception:
                logger.debug("Checkpoint %s unreadable, trying next", ckpt_name)
                continue
        return None

    # ── JSON serialization ──────────────────────────────────────────

    def _to_json_str(self) -> str:
        """Serialize state to a versioned JSON string."""
        data = self.__getstate__()  # strips history, transient fields
        doc = _build_state_serialization_doc(data)
        return json.dumps(doc, separators=(",", ":"))

    @staticmethod
    def _from_raw(raw: str) -> State:
        """Deserialize state from JSON.

        Legacy pickle/base64 format is no longer supported.
        """
        stripped = raw.strip()
        if not stripped.startswith("{"):
            msg = (
                "State file is in legacy pickle/base64 format which is no "
                "longer supported.  Delete the checkpoint and start a fresh "
                "session."
            )
            raise ValueError(msg)
        return State._from_json_str(stripped)

    @staticmethod
    def _from_json_str(raw: str) -> State:
        """Reconstruct a State from versioned JSON."""
        doc = json.loads(raw)
        version = doc.get("_schema_version", 0)
        if version < 1:
            raise ValueError(f"Unknown state schema version: {version}")

        state = State()
        _apply_state_scalars(state, doc)
        _apply_state_enums_and_dicts(state, doc)
        _apply_state_turn_signals(state, doc)
        _apply_state_control_flags(state, doc)
        _apply_state_metrics(state, doc)
        _apply_state_plan(state, doc)
        return state

    def __getstate__(self) -> dict:
        """Return the picklable state while omitting large transient history."""
        state = self.__dict__.copy()
        state["history"] = []
        state.pop("_history_checksum", None)
        state.pop("_history_version", None)
        state.pop("_view_history_version", None)
        state.pop("_cached_first_user_message", None)
        state.pop("_view", None)
        state.pop("restore_provenance", None)
        state.pop("iteration", None)
        state.pop("local_iteration", None)
        state.pop("max_iterations", None)
        state.pop("traffic_control_state", None)
        state.pop("local_metrics", None)
        state.pop("delegates", None)
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore state from serialized data and rebuild control flags."""
        self.__dict__.update(state)
        if not hasattr(self, "history"):
            self.history = []
        if not hasattr(self, "iteration_flag"):
            self.iteration_flag = IterationControlFlag(
                limit_increase_amount=100,
                current_value=0,
                max_value=100,
            )
        if not hasattr(self, "budget_flag"):
            self.budget_flag = None
        self._history_version = 0
        self._view_history_version = -1
        self._view = View.from_events([])
        self.history = self.history

    def _process_user_message_event(
        self,
        event: MessageAction,
    ) -> tuple[str, list[str] | None]:
        """Process a user message event and extract content and image URLs."""
        return event.content, event.image_urls

    def _check_for_finish_action(
        self,
        event: Event,
        last_user_message: str | None,
    ) -> tuple[str | None, list[str] | None] | None:
        """Check if event is a finish action and return appropriate result."""
        if isinstance(event, PlaybookFinishAction) and last_user_message is not None:
            return (last_user_message, None)
        return None

    def _find_user_intent_from_events(self) -> tuple[str | None, list[str] | None]:
        """Find user intent by processing events in reverse order."""
        last_user_message = None
        last_user_message_image_urls: list[str] | None = []

        for event in reversed(self.view):
            if isinstance(event, MessageAction) and event.source == "user":
                last_user_message, last_user_message_image_urls = (
                    self._process_user_message_event(event)
                )
            elif isinstance(event, PlaybookFinishAction):
                finish_result = self._check_for_finish_action(event, last_user_message)
                if finish_result is not None:
                    return finish_result

        return (last_user_message, last_user_message_image_urls)

    def get_current_user_intent(self) -> tuple[str | None, list[str] | None]:
        """Returns the latest user message and image(if provided) that appears after a FinishAction, or the first (the task) if nothing was finished yet."""
        return self._find_user_intent_from_events()

    def get_last_agent_message(self) -> MessageAction | None:
        """Get most recent message from agent in conversation history.

        Returns:
            Last agent message, or None if no agent messages

        """
        return next(
            (
                event
                for event in reversed(self.view)
                if isinstance(event, MessageAction)
                and event.source == EventSource.AGENT
            ),
            None,
        )

    def get_last_user_message(self) -> MessageAction | None:
        """Get most recent message from user in conversation history.

        Returns:
            Last user message, or None if no user messages

        """
        return next(
            (
                event
                for event in reversed(self.view)
                if isinstance(event, MessageAction) and event.source == EventSource.USER
            ),
            None,
        )

    def to_llm_metadata(self, model_name: str, agent_name: str) -> dict:
        """Convert state to metadata dict for LLM tracing/logging.

        Args:
            model_name: Name of LLM model being used
            agent_name: Name of agent being traced

        Returns:
            Dictionary with session, version, and tag metadata

        """
        tags = [
            f"model:{model_name}",
            f"agent:{agent_name}",
            f"web_host:{os.environ.get('WEB_HOST', 'unspecified')}",
            f"APP_version:{backend.__version__}",
        ]
        return {
            "session_id": self.session_id,
            "trace_version": backend.__version__,
            "trace_user_id": self.user_id,
            # OpenAI-compatible metadata payloads require plain string values.
            "tags": ",".join(tags),
        }

    def get_local_step(self):
        """Get iteration count for current subtask (delegate).

        Returns:
            Local step count relative to parent, or global count if no parent

        """
        if not self.parent_iteration:
            return self.iteration_flag.current_value
        return self.iteration_flag.current_value - self.parent_iteration

    def get_local_metrics(self):
        """Get metrics for current subtask (delegate).

        Returns:
            Local metrics relative to parent snapshot, or global if no parent

        """
        if not self.parent_metrics_snapshot:
            return self.metrics
        return self.metrics.diff(self.parent_metrics_snapshot)

    @property
    def view(self) -> View:
        """Get filtered view of conversation history for agent.

        Returns:
            View object containing relevant events for agent context

        """
        history_version = getattr(self, "_history_version", 0)
        old_history_version = getattr(self, "_view_history_version", -1)
        if history_version != old_history_version:
            self._view_history_version = history_version
            self._view = View.from_events(self.history)
        return self._view
