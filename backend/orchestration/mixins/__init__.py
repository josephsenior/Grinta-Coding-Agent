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

from backend.orchestration.mixins.action import (  # noqa: F401, E402
    _SessionOrchestratorActionMixin,
)
from backend.orchestration.mixins.lifecycle import (  # noqa: F401, E402
    _SessionOrchestratorLifecycleMixin,
)
from backend.orchestration.mixins.parallel import (  # noqa: F401, E402
    _SessionOrchestratorParallelMixin,
)
from backend.orchestration.mixins.state import (  # noqa: F401, E402
    _SessionOrchestratorStateMixin,
)
from backend.orchestration.mixins.step import (  # noqa: F401, E402
    _SessionOrchestratorStepMixin,
)
from backend.orchestration.mixins.watchdog import (  # noqa: F401, E402
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


def __getattr__(name: str):
    """Backward-compatible submodule aliases used by unit-test patch paths."""
    import importlib

    aliases = {
        'action_mixin': 'backend.orchestration.mixins.action',
        'lifecycle_mixin': 'backend.orchestration.mixins.lifecycle',
        'parallel_mixin': 'backend.orchestration.mixins.parallel',
        'state_mixin': 'backend.orchestration.mixins.state',
        'step_mixin': 'backend.orchestration.mixins.step',
        'watchdog_mixin': 'backend.orchestration.mixins.watchdog',
    }
    target = aliases.get(name)
    if target is not None:
        return importlib.import_module(target)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
