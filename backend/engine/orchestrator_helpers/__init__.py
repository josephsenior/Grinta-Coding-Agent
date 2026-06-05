"""Internal helper modules for :class:`backend.engine.orchestrator.Orchestrator`.

The orchestrator class delegates each concern to a dedicated private module:

- :mod:`backend.engine.orchestrator_helpers._orchestrator_helpers` — top-level
  utility functions (counter normalizers, history trimmers).
- :mod:`backend.engine.orchestrator_helpers._orchestrator_actions` — pending
  and deferred action queue management.
- :mod:`backend.engine.orchestrator_helpers._orchestrator_prompts` — prompt
  manager creation and MCP tool wiring.
- :mod:`backend.engine.orchestrator_helpers._orchestrator_condensation` —
  condensation event emission and post-condensation recovery.
- :mod:`backend.engine.orchestrator_helpers._orchestrator_recovery` — step
  and tool-error recovery cascades.
- :mod:`backend.engine.orchestrator_helpers._orchestrator_protocol` —
  protocol-mode fallback synthesis.
- :mod:`backend.engine.orchestrator_helpers._orchestrator_step` — ``step``,
  ``astep``, and the underlying LLM-step primitives.

All symbols are private (leading underscore) and intended to be imported only
by :mod:`backend.engine.orchestrator`.
"""
