"""State models and helpers for tracking agent conversations."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import backend
from backend.controller.state.control_flags import (
    BudgetControlFlag,
    IterationControlFlag,
)
from backend.core.logger import forge_logger as logger
from backend.core.schemas import AgentState
from backend.events.action import MessageAction
from backend.events.action.agent import PlaybookFinishAction
from backend.events.event import Event, EventSource
from backend.llm.metrics import Metrics
from backend.memory.view import View
from backend.storage.locations import get_conversation_agent_state_filename

if TYPE_CHECKING:
    from backend.server.services.conversation_stats import ConversationStats
    from backend.storage.files import FileStore

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


class TrafficControlState:
    """Track pause/resume state for agent loops and manage iteration counters."""

    NORMAL = "normal"
    THROTTLING = "throttling"
    PAUSED = "paused"


@dataclass
class State:
    """Represents the running state of an agent in the Forge system, saving data of its operation and memory.

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
        self.conversation_stats = conversation_stats

    @staticmethod
    def _checkpoint_dir(sid: str, user_id: str | None) -> str:
        """Return the directory path for state checkpoints."""
        from backend.storage.locations import get_conversation_dir

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

        # --- Try the primary file first ---
        try:
            raw = file_store.read(
                get_conversation_agent_state_filename(sid, user_id),
            )
        except FileNotFoundError as e:
            if not user_id:
                # Before giving up, try checkpoints
                state = State._restore_from_checkpoints(file_store, sid, user_id)
                if state is not None:
                    return state
                msg = f"Could not restore state from session file for sid: {sid}"
                raise FileNotFoundError(msg) from e
            filename = get_conversation_agent_state_filename(sid)
            try:
                raw = file_store.read(filename)
            except FileNotFoundError:
                state = State._restore_from_checkpoints(file_store, sid, user_id)
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
            state = State._restore_from_checkpoints(file_store, sid, user_id)
            if state is None:
                raise primary_error

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
                raw = file_store.read(f"{ckpt_dir}{ckpt_name}")
                state = State._from_raw(raw)
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
        doc: dict[str, Any] = {"_schema_version": STATE_SCHEMA_VERSION}

        # Simple scalar fields
        for key in (
            "session_id",
            "user_id",
            "confirmation_mode",
            "delegate_level",
            "start_id",
            "end_id",
            "parent_iteration",
            "last_error",
        ):
            if key in data:
                doc[key] = data[key]

        # Enum fields
        for key in ("agent_state", "resume_state"):
            val = data.get(key)
            doc[key] = val.value if isinstance(val, Enum) else val

        # Dict fields (inputs, outputs, extra_data)
        for key in ("inputs", "outputs", "extra_data"):
            doc[key] = data.get(key, {})

        # Turn signals (typed)
        ts = data.get("turn_signals")
        doc["turn_signals"] = asdict(ts) if ts else None

        # ControlFlag dataclasses
        flag = data.get("iteration_flag")
        doc["iteration_flag"] = asdict(flag) if flag else None

        bflag = data.get("budget_flag")
        doc["budget_flag"] = asdict(bflag) if bflag else None

        # Metrics — use its own .get() → dict
        metrics = data.get("metrics")
        doc["metrics"] = (
            metrics.get() if metrics is not None and hasattr(metrics, "get") else None
        )

        pms = data.get("parent_metrics_snapshot")
        doc["parent_metrics_snapshot"] = (
            pms.get() if pms is not None and hasattr(pms, "get") else None
        )

        plan = data.get("plan")
        doc["plan"] = (
            asdict(plan) if plan and hasattr(plan, "steps") else None
        )

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
            msg = f"Unknown state schema version: {version}"
            raise ValueError(msg)

        state = State()

        # Simple scalars
        for key in (
            "session_id",
            "user_id",
            "confirmation_mode",
            "delegate_level",
            "start_id",
            "end_id",
            "parent_iteration",
            "last_error",
        ):
            if key in doc:
                setattr(state, key, doc[key])

        # Enum fields
        agent_state_val = doc.get("agent_state")
        if agent_state_val is not None:
            state.set_agent_state(
                AgentState(agent_state_val),
                source="State._from_json_str",
            )

        resume_state_val = doc.get("resume_state")
        state.resume_state = AgentState(resume_state_val) if resume_state_val else None

        # Dict fields
        state.inputs = doc.get("inputs", {})
        state.outputs = doc.get("outputs", {})
        state.extra_data = doc.get("extra_data", {})

        # Turn signals
        ts = doc.get("turn_signals")
        if isinstance(ts, dict):
            state.turn_signals = TurnSignals(
                planning_directive=ts.get("planning_directive"),
                memory_pressure=ts.get("memory_pressure"),
            )

        # ControlFlags
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

        # Metrics
        metrics_dict = doc.get("metrics")
        if isinstance(metrics_dict, dict):
            m = Metrics()
            m.__setstate__(metrics_dict)
            state.metrics = m

        pms_dict = doc.get("parent_metrics_snapshot")
        if isinstance(pms_dict, dict):
            pms = Metrics()
            pms.__setstate__(pms_dict)
            state.parent_metrics_snapshot = pms

        plan_dict = doc.get("plan")
        if isinstance(plan_dict, dict):
            try:
                # Helper to recursively rebuild PlanSteps
                def _build_step(d: dict) -> PlanStep:
                    return PlanStep(
                        id=d["id"],
                        description=d["description"],
                        status=d.get("status", "pending"),
                        result=d.get("result"),
                        subtasks=[_build_step(s) for s in d.get("subtasks", [])],
                        tags=d.get("tags", []),
                    )
                
                steps = [_build_step(s) for s in plan_dict.get("steps", [])]
                state.plan = ActivePlan(
                    steps=steps,
                    title=plan_dict.get("title", "Current Plan"),
                )
            except Exception as e:
                logger.warning("Failed to restore plan from state: %s", e)

        return state

    def __getstate__(self) -> dict:
        """Return the picklable state while omitting large transient history."""
        state = self.__dict__.copy()
        state["history"] = []
        state.pop("_history_checksum", None)
        state.pop("_view", None)
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
        return {
            "session_id": self.session_id,
            "trace_version": backend.__version__,
            "trace_user_id": self.user_id,
            "tags": [
                f"model:{model_name}",
                f"agent:{agent_name}",
                f"web_host:{os.environ.get('WEB_HOST', 'unspecified')}",
                f"FORGE_version:{backend.__version__}",
            ],
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
        history_checksum = len(self.history)
        old_history_checksum = getattr(self, "_history_checksum", -1)
        if history_checksum != old_history_checksum:
            self._history_checksum = history_checksum
            self._view = View.from_events(self.history)
        return self._view
