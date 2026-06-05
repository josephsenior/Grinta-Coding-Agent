"""Session-lifecycle mixin for :class:`backend.cli.repl.Repl`.

Holds the agent-idle wait loop, interrupt handler, session resume logic and
confirmation prompt. Method bodies are extracted into focused helper
modules:

* :mod:`backend.cli._repl._session_lifecycle_wait` — wait loop, idle/timeout
  helpers, notification dispatch.
* :mod:`backend.cli._repl._session_lifecycle_resume` — session resume steps.
* :mod:`backend.cli._repl._session_lifecycle_confirm` — interrupt and Y/N
  confirmation.

The mixin assumes the host class provides:

* attributes: ``_renderer``, ``_console``, ``_controller``, ``_event_stream``,
  ``_runtime``, ``_acquire_result``, ``_memory``, ``_reasoning``, ``_hud``,
  ``_llm_registry``, ``_agent``, ``_conversation_stats``;
"""

from __future__ import annotations

import logging
import time  # noqa: F401  (test patch target: session_lifecycle_mixin.time.monotonic)
from typing import TYPE_CHECKING, Any, cast

from backend.cli._repl._session_lifecycle_confirm import (
    _cancel_agent,
    _handle_confirmation,
)
from backend.cli._repl._session_lifecycle_resume import (
    _build_resume_controller,
    _resolve_resume_target,
    _resume_session,
    _setup_resume_runtime,
    _validate_resume_bootstrap_state,
    _wire_resume_runtime_state,
)
from backend.cli._repl._session_lifecycle_wait import (
    _active_timeout,
    _coerce_env_int,
    _drain_renderer_until_settled,
    _fire_idle_notification,
    _handle_agent_hard_timeout,
    _handle_idle_or_confirmation,
    _resolve_hard_timeouts,
    _wait_for_agent_idle,
)

if TYPE_CHECKING:
    from backend.cli._typing import SessionLifecycleHost

    _SessionLifecycleBase = SessionLifecycleHost
else:
    _SessionLifecycleBase = object

from backend.cli._typing import SessionLifecycleHost  # noqa: E402
from backend.core.config import AppConfig  # noqa: E402
from backend.core.enums import AgentState  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ['SessionLifecycleMixin']


class SessionLifecycleMixin(_SessionLifecycleBase):
    """Mixin providing agent-wait, interrupt, resume and confirmation flows."""

    _controller: Any
    _memory: Any
    _acquire_result: Any
    _event_stream: Any
    _runtime: Any
    _renderer: Any
    _console: Any
    _hud: Any
    _reasoning: Any
    _suppress_low_risk_confirmations: bool

    # -- wait for agent to be idle -----------------------------------------

    _IDLE_AGENT_STATES: frozenset[AgentState] = frozenset(
        {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
            AgentState.REJECTED,
        }
    )

    @staticmethod
    def _coerce_env_int(name: str, default: int = 0, *, floor: int = 0) -> int:
        return _coerce_env_int(name, default, floor=floor)

    @classmethod
    def _resolve_hard_timeouts(cls) -> tuple[int, int]:
        return _resolve_hard_timeouts()

    @staticmethod
    def _active_timeout(
        controller: Any,
        hard_timeout: int,
        cmd_timeout: int,
    ) -> int:
        return _active_timeout(controller, hard_timeout, cmd_timeout)

    async def _wait_for_agent_idle(self, controller: Any, agent_task: Any) -> None:
        await _wait_for_agent_idle(
            cast(SessionLifecycleHost, self),
            controller,
            agent_task,
        )

    async def _handle_idle_or_confirmation(
        self,
        controller: Any,
        renderer: Any,
        state: AgentState,
    ) -> bool:
        return await _handle_idle_or_confirmation(
            cast(SessionLifecycleHost, self),
            controller,
            renderer,
            state,
        )

    @staticmethod
    def _fire_idle_notification(state: AgentState) -> None:
        _fire_idle_notification(state)

    async def _handle_agent_hard_timeout(
        self,
        renderer: Any,
        agent_task: Any,
        active_timeout: int,
    ) -> None:
        await _handle_agent_hard_timeout(
            cast(SessionLifecycleHost, self),
            renderer,
            agent_task,
            active_timeout,
        )

    async def _drain_renderer_until_settled(
        self,
        renderer: Any,
        *,
        settle_delay: float = 0.05,
        max_passes: int = 4,
    ) -> None:
        await _drain_renderer_until_settled(
            renderer,
            settle_delay=settle_delay,
            max_passes=max_passes,
        )

    # -- interrupt handler -------------------------------------------------

    async def _cancel_agent(self, agent_task: Any) -> None:
        await _cancel_agent(cast(SessionLifecycleHost, self), agent_task)

    # -- session resume ----------------------------------------------------

    async def _resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, Any] | None:
        return await _resume_session(
            cast(SessionLifecycleHost, self),
            target,
            config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def _validate_resume_bootstrap_state(
        self,
    ) -> tuple[Any, Any, Any] | None:
        return _validate_resume_bootstrap_state(cast(SessionLifecycleHost, self))

    def _resolve_resume_target(
        self,
        target: str,
        config: AppConfig,
    ) -> str | None:
        return _resolve_resume_target(
            cast(SessionLifecycleHost, self), target, config
        )

    def _setup_resume_runtime(
        self,
        config: AppConfig,
        llm_registry: Any,
        agent: Any,
        resolved_id: str,
    ) -> tuple[Any, Any, Any, Any] | None:
        return _setup_resume_runtime(
            cast(SessionLifecycleHost, self),
            config,
            llm_registry,
            agent,
            resolved_id,
        )

    async def _wire_resume_runtime_state(
        self,
        config: AppConfig,
        runtime: Any,
        agent: Any,
        resolved_id: str,
        repo_directory: Any,
        acquire_result: Any,
        event_stream: Any,
    ) -> bool:
        return await _wire_resume_runtime_state(
            cast(SessionLifecycleHost, self),
            config,
            runtime,
            agent,
            resolved_id,
            repo_directory,
            acquire_result,
            event_stream,
        )

    def _build_resume_controller(
        self,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        create_controller: Any,
        create_status_callback: Any,
    ) -> Any:
        return _build_resume_controller(
            cast(SessionLifecycleHost, self),
            agent,
            runtime,
            config,
            conversation_stats,
            create_controller,
            create_status_callback,
        )

    # -- confirmation handler ----------------------------------------------

    async def _handle_confirmation(self, controller: Any) -> None:
        await _handle_confirmation(cast(SessionLifecycleHost, self), controller)
