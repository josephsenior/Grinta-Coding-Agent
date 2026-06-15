"""Mixins that compose :class:`backend.orchestration.SessionOrchestrator`.

The orchestrator class itself is split across a small set of single-purpose
mixin modules (one per concern: action handling, lifecycle, parallel
execution, state management, and step execution). This package keeps those
mixin modules grouped together so the composition of
:class:`SessionOrchestrator` is easy to discover and navigate.

All modules are private (leading underscore) and intended to be imported
only by :mod:`backend.orchestration.session_orchestrator`.
"""

from __future__ import annotations

from backend.orchestration.session_orchestrator_mixins._session_orchestrator_action_mixin import (  # noqa: F401, E402
    _SessionOrchestratorActionMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_lifecycle_mixin import (  # noqa: F401, E402
    _SessionOrchestratorLifecycleMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_parallel_mixin import (  # noqa: F401, E402
    _SessionOrchestratorParallelMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_state_mixin import (  # noqa: F401, E402
    _SessionOrchestratorStateMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_step_mixin import (  # noqa: F401, E402
    _SessionOrchestratorStepMixin,
)
from backend.orchestration.session_orchestrator_mixins._session_orchestrator_watchdog_mixin import (  # noqa: F401, E402
    _SessionOrchestratorWatchdogMixin,
)

__all__ = [
    '_SessionOrchestratorActionMixin',
    '_SessionOrchestratorLifecycleMixin',
    '_SessionOrchestratorParallelMixin',
    '_SessionOrchestratorStateMixin',
    '_SessionOrchestratorStepMixin',
    '_SessionOrchestratorWatchdogMixin',
]
