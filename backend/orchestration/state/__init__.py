"""Session state model, control flags, history tracker, and checkpoint manager.

Re-exports the public state-management types for ergonomic imports from
``backend.orchestration.state`` and to mirror the explicit-package convention
used by ``backend.orchestration.services``.
"""

from backend.orchestration.state.control_flags import (
    BudgetControlFlag,
    ControlFlag,
    IterationControlFlag,
)
from backend.orchestration.state.session_checkpoint_manager import (
    SessionCheckpointManager,
)
from backend.orchestration.state.state import (
    ActivePlan,
    PlanStep,
    RestoreProvenance,
    State,
    TrackedHistoryList,
    TrafficControlState,
    TurnSignals,
)
from backend.orchestration.state.state_tracker import (
    MAX_HISTORY_BYTES,
    MAX_HISTORY_EVENTS,
    StateTracker,
)

__all__ = [
    'ActivePlan',
    'BudgetControlFlag',
    'ControlFlag',
    'IterationControlFlag',
    'MAX_HISTORY_BYTES',
    'MAX_HISTORY_EVENTS',
    'PlanStep',
    'RestoreProvenance',
    'SessionCheckpointManager',
    'State',
    'StateTracker',
    'TrafficControlState',
    'TrackedHistoryList',
    'TurnSignals',
]
