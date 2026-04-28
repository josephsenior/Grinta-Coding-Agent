"""Engine-facing re-export of the orchestration ``State`` type.

The concrete ``State`` implementation lives in
:mod:`backend.orchestration.state.state` because it depends on
orchestration-only services (``ConversationStats``, ``FileStore``,
``ControlFlag`` machinery, etc.). Engine code, however, only needs the
type for annotations and a few read/ack methods (``history``,
``to_llm_metadata``, ``ack_planning_directive``, ``ack_memory_pressure``,
``get_last_user_message``).

Re-exporting through this contracts module keeps engine source files
free of ``from backend.orchestration...`` imports, which:

- Makes the layered architecture explicit (engine ⇏ orchestration at the
  import-graph level).
- Lets future moves of the implementation file land without touching
  every engine import site.
- Gives layer-boundary linters a single place to whitelist.
"""

from __future__ import annotations

from backend.orchestration.state.state import (  # noqa: F401
    State,
    normalize_plan_step_payload,
)

__all__ = ['State', 'normalize_plan_step_payload']
