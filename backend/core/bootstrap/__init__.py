"""Bootstrap modules that wire together cross-layer components.

These modules are intentionally allowed to import from higher layers
(controller, engines, memory, runtime) because they serve as the
application composition root. They are the only modules in ``core``
that cross layer boundaries.

Modules:
    agent_control_loop - Polling loop that drives the agent until a terminal state
    main               - CLI / headless entry point, run_controller orchestration
    setup              - Factory functions: create_agent, create_controller, create_memory, create_runtime
"""

from backend.core.bootstrap.agent_control_loop import run_agent_until_done
from backend.core.bootstrap.setup import (
    create_agent,
    create_controller,
    create_memory,
    create_runtime,
    filter_plugins_by_config,
    generate_sid,
    get_provider_tokens,
    initialize_repository_for_runtime,
)

__all__ = [
    "create_agent",
    "create_controller",
    "create_memory",
    "create_runtime",
    "filter_plugins_by_config",
    "generate_sid",
    "get_provider_tokens",
    "initialize_repository_for_runtime",
    "run_agent_until_done",
]
