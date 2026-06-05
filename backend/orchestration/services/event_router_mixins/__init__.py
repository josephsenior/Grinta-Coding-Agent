"""Mixins that compose :class:`backend.orchestration.services.EventRouterService`.

The :class:`EventRouterService` class is split into a small set of
single-purpose mixin modules (one per concern: actions, state, user
message, delegate) plus a small delegate-helper module. This package
keeps those mixin modules grouped together so the composition of
:class:`EventRouterService` is easy to discover and navigate.

All modules are private (leading underscore) and intended to be imported
only by :mod:`backend.orchestration.services.event_router_service`.
"""

from __future__ import annotations

from backend.orchestration.services.event_router_mixins._event_router_actions_mixin import (  # noqa: E402, F401
    _EventRouterActionsMixin,
)
from backend.orchestration.services.event_router_mixins._event_router_delegate_mixin import (  # noqa: E402, F401
    _EventRouterDelegateMixin,
)
from backend.orchestration.services.event_router_mixins._event_router_state_mixin import (  # noqa: E402, F401
    _EventRouterStateMixin,
)
from backend.orchestration.services.event_router_mixins._event_router_user_message_mixin import (  # noqa: E402, F401
    _EventRouterUserMessageMixin,
)

__all__ = [
    '_EventRouterActionsMixin',
    '_EventRouterDelegateMixin',
    '_EventRouterStateMixin',
    '_EventRouterUserMessageMixin',
]
