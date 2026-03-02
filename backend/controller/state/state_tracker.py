from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.controller.state.control_flags import (
    BudgetControlFlag,
    IterationControlFlag,
)
from backend.controller.state.state import State
from backend.core.logger import forge_logger as logger
from backend.events.action.agent import ChangeAgentStateAction
from backend.events.action.empty import NullAction
from backend.events.event_filter import EventFilter
from backend.events.observation.agent import AgentStateChangedObservation
from backend.events.observation.empty import NullObservation
from backend.events.serialization.event import event_to_trajectory

# Maximum number of events retained in state.history at runtime.
# The condenser / View system controls what the LLM actually sees;
# this cap prevents user-facing context memory growth.
MAX_HISTORY_EVENTS: int = 10_000

# Estimated byte-size cap for the in-memory history list.
# When the rough size estimate exceeds this, oldest events are trimmed
# regardless of the count cap.
MAX_HISTORY_BYTES: int = 200 * 1024 * 1024  # 200 MB

if TYPE_CHECKING:
    from backend.events.event import Event
    from backend.events.stream import EventStream
    from backend.api.services.conversation_stats import ConversationStats
    from backend.storage.files import FileStore


class StateTracker:
    """Manages and synchronizes the state of an agent throughout its lifecycle.

    It is responsible for:
    1. Maintaining agent state persistence across sessions
    2. Managing agent history by filtering and tracking relevant events (previously done in the agent controller)
    3. Synchronizing metrics between the controller and LLM components
    4. Updating control flags for budget and iteration limits

    """

    def __init__(
        self, sid: str | None, file_store: FileStore | None, user_id: str | None
    ) -> None:
        """Initialize state tracker.

        Args:
            sid: Session ID for this tracker
            file_store: File storage backend for persisting state
            user_id: ID of user associated with this session

        """
        self.sid = sid
        self.file_store = file_store
        self.user_id = user_id
        self.agent_history_filter = EventFilter(
            exclude_types=(
                NullAction,
                NullObservation,
                ChangeAgentStateAction,
                AgentStateChangedObservation,
            ),
            exclude_hidden=True,
        )

    # pylint: disable=R0917
    def set_initial_state(
        self,
        session_id: str,
        state: State | None,
        conversation_stats: ConversationStats,
        max_iterations: int,
        max_budget_per_task: float | None,
        confirmation_mode: bool = False,
    ) -> None:
        """Set the initial state for the agent.

        Uses previous session state, parent state, or creates a new state.

        Args:
            session_id: The session ID for the agent.
            state: The state to initialize with, or None to create a new state.
            conversation_stats: Statistics for the conversation.
            max_iterations: The maximum number of iterations allowed for the task.
            max_budget_per_task: The maximum budget allowed for the task.
            confirmation_mode: Whether to enable confirmation mode.

        """
        if state is None:
            self.state = State(
                session_id=session_id.removesuffix("-delegate"),
                user_id=self.user_id,
                inputs={},
                conversation_stats=conversation_stats,
                iteration_flag=IterationControlFlag(
                    limit_increase_amount=max_iterations,
                    current_value=0,
                    max_value=max_iterations,
                ),
                budget_flag=(
                    BudgetControlFlag(
                        limit_increase_amount=max_budget_per_task,
                        current_value=0,
                        max_value=max_budget_per_task,
                    )
                    if max_budget_per_task
                    else None
                ),
                confirmation_mode=confirmation_mode,
            )
            self.state.start_id = 0
            logger.info(
                "AgentController %s - created new state. start_id: %s",
                session_id,
                self.state.start_id,
            )
        else:
            self.state = state
            if self.state.start_id <= -1:
                self.state.start_id = 0
            state.conversation_stats = conversation_stats

    def _init_history(self, event_stream: EventStream) -> None:
        """Initializes the agent's history from the event stream.

        The history is a list of events that:
        - Excludes events of types listed in self.filter_out
        - Excludes events with hidden=True attribute
        """
        start_id, end_id = self._get_history_range(event_stream)

        if not self._validate_history_range(start_id, end_id):
            return

        self.state.history = self._fetch_events_from_stream(
            event_stream, start_id, end_id
        )
        self.state.start_id = start_id

    def _get_history_range(self, event_stream: EventStream) -> tuple[int, int]:
        """Get the start and end ID range for history."""
        start_id = max(self.state.start_id, 0)
        end_id = (
            self.state.end_id
            if self.state.end_id >= 0
            else event_stream.get_latest_event_id()
        )
        return start_id, end_id

    def _validate_history_range(self, start_id: int, end_id: int) -> bool:
        """Validate the history range and set empty history if invalid."""
        if start_id > end_id + 1:
            logger.warning(
                "start_id %s is greater than end_id + 1 (%s). History will be empty.",
                start_id,
                end_id + 1,
            )
            self.state.history = []
            return False
        return True

    def _fetch_events_from_stream(
        self, event_stream: EventStream, start_id: int, end_id: int
    ) -> list[Event]:
        """Fetch events from the event stream."""
        return list(
            event_stream.search_events(
                start_id=start_id,
                end_id=end_id,
                reverse=False,
                filter=self.agent_history_filter,
            ),
        )

    def set_conversation_stats(self, conversation_stats: ConversationStats) -> None:
        self.state.conversation_stats = conversation_stats

    def close(self, event_stream: EventStream) -> None:
        """Finalize state history when agent controller closes.

        Saves complete event history to state for persistence.

        Args:
            event_stream: Event stream to extract history from

        """
        start_id = max(self.state.start_id, 0)
        end_id = (
            self.state.end_id
            if self.state.end_id >= 0
            else event_stream.get_latest_event_id()
        )
        self.state.history = list(
            event_stream.search_events(
                start_id=start_id,
                end_id=end_id,
                reverse=False,
                filter=self.agent_history_filter,
            ),
        )

    def add_history(self, event: Event) -> None:
        """Add event to state history if it passes filter criteria.

        Enforces two sliding-window caps:
        1. **Count cap** — oldest 25% trimmed when ``MAX_HISTORY_EVENTS``
           is exceeded.
        2. **Byte-size cap** — oldest 25% trimmed when the rough
           in-memory size estimate exceeds ``MAX_HISTORY_BYTES``.  This
           catches pathological cases where a small number of very large
           events (huge command output, file contents) consume hundreds
           of MB.

        Args:
            event: Event to potentially add to history

        """
        if self.agent_history_filter.include(event):
            self.state.history.append(event)
            self._maybe_trim_history()

    def _maybe_trim_history(self) -> None:
        """Trim history if count or estimated byte-size caps are exceeded."""
        history = self.state.history
        need_trim = False
        reason = ""

        if len(history) > MAX_HISTORY_EVENTS:
            need_trim = True
            reason = f"count {len(history)} > {MAX_HISTORY_EVENTS}"
        elif len(history) > 100:  # only estimate when list is non-trivial
            estimated_bytes = self._estimate_history_bytes(history)
            if estimated_bytes > MAX_HISTORY_BYTES:
                need_trim = True
                reason = f"estimated size {estimated_bytes // (1024 * 1024)}MB > {MAX_HISTORY_BYTES // (1024 * 1024)}MB"

        if need_trim:
            trim_count = max(len(history) // 4, 1)
            self.state.history = history[trim_count:]
            logger.debug(
                "Trimmed %d oldest events from state.history (%s, now %d)",
                trim_count,
                reason,
                len(self.state.history),
            )

    @staticmethod
    def _estimate_history_bytes(history: list) -> int:
        """Rough byte-size estimate for the history list.

        Uses ``sys.getsizeof`` on string-heavy fields (message, content)
        as a cheap proxy — avoids deep traversal which would be too slow
        to run on every event insertion.
        """
        import sys

        total = 0
        # Sample every 10th event for speed, multiply by count
        sample_step = max(1, len(history) // 100)
        sample_total = 0
        sample_count = 0
        for i in range(0, len(history), sample_step):
            evt = history[i]
            size = sys.getsizeof(evt)
            # Also count large string fields if present
            for attr in ("content", "message", "output", "text"):
                val = getattr(evt, attr, None)
                if isinstance(val, str):
                    size += len(val)
            sample_total += size
            sample_count += 1
        if sample_count > 0:
            total = (sample_total // sample_count) * len(history)
        return total

    def get_trajectory(self, include_screenshots: bool = False) -> list[dict]:
        """Convert state history to trajectory format for export.

        Args:
            include_screenshots: Whether to include screenshot data

        Returns:
            List of trajectory event dictionaries

        """
        trajectory: list[dict[str, Any]] = []
        for event in self.state.history:
            serialized = event_to_trajectory(event, include_screenshots)
            if serialized is not None:
                trajectory.append(serialized)
        return trajectory

    def maybe_increase_control_flags_limits(self, headless_mode: bool) -> None:
        """Conditionally increase iteration and budget limits.

        Used when agent needs more resources to complete task.

        Args:
            headless_mode: Whether running in headless mode

        """
        self.state.iteration_flag.increase_limit(headless_mode)
        if self.state.budget_flag:
            self.state.budget_flag.increase_limit(headless_mode)

    def get_metrics_snapshot(self):
        """Deep copy of metrics.

        This serves as a snapshot for the parent's metrics at the time a delegate is created
        It will be stored and used to compute local metrics for the delegate
        (since delegates now accumulate metrics from where its parent left off).
        """
        return self.state.metrics.copy()

    def save_state(self) -> None:
        """Save's current state to persistent store."""
        if self.sid and self.file_store:
            self.state.save_to_session(self.sid, self.file_store, self.user_id)
        if self.state.conversation_stats:
            self.state.conversation_stats.save_metrics()

    def run_control_flags(self) -> None:
        """Performs one step of the control flags."""
        self.state.iteration_flag.step()
        if self.state.budget_flag:
            self.state.budget_flag.step()

    def sync_budget_flag_with_metrics(self) -> None:
        """Ensures that budget flag is up to date with accumulated costs from llm completions.

        Budget flag will monitor for when budget is exceeded.
        """
        if self.state.budget_flag and self.state.conversation_stats:
            self.state.budget_flag.current_value = (
                self.state.conversation_stats.get_combined_metrics().accumulated_cost
            )
