"""Event routing service for SessionOrchestrator.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in SessionOrchestrator._on_event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator


_DELEGATE_PROGRESS_STATUS = 'delegate_progress'


from backend.orchestration.services.event_router_mixins._event_router_actions_mixin import (  # noqa: F401, E402
    _EventRouterActionsMixin,
)

# Re-export helper functions for backward compatibility (tests import these
# from backend.orchestration.services.event_router_service).
from backend.orchestration.services.event_router_mixins._event_router_delegate_helpers import (  # noqa: F401, E402
    _build_delegate_progress_observation,
    _summarize_delegate_worker_event,
)
from backend.orchestration.services.event_router_mixins._event_router_delegate_mixin import (  # noqa: F401, E402
    _EventRouterDelegateMixin,
)
from backend.orchestration.services.event_router_mixins._event_router_state_mixin import (  # noqa: F401, E402
    _EventRouterStateMixin,
)
from backend.orchestration.services.event_router_mixins._event_router_user_message_mixin import (  # noqa: F401, E402
    _EventRouterUserMessageMixin,
)


class EventRouterService(
    _EventRouterStateMixin,
    _EventRouterActionsMixin,
    _EventRouterUserMessageMixin,
    _EventRouterDelegateMixin,
):
    """Routes events to the correct handler on SessionOrchestrator.

    Separates the *what-to-do-with-events* concern from the controller's
    step-execution and lifecycle management.
    """

    def __init__(self, controller: SessionOrchestrator) -> None:
        self._ctrl = controller
