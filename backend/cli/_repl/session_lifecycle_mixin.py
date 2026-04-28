"""Session-lifecycle mixin for :class:`backend.cli.repl.Repl`.

Holds the agent-idle wait loop, interrupt handler, session resume logic and
confirmation prompt — extracted from :mod:`backend.cli.repl` to keep the main
module close to the project's per-file LOC budget.

The mixin assumes the host class provides:

* attributes: ``_renderer``, ``_console``, ``_controller``, ``_event_stream``,
  ``_runtime``, ``_acquire_result``, ``_memory``, ``_reasoning``, ``_hud``,
  ``_llm_registry``, ``_agent``, ``_conversation_stats``;
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import Any, cast

from backend.cli.confirmation import build_confirmation_action, render_confirmation
from backend.core.config import AppConfig
from backend.core.enums import AgentState, EventSource

logger = logging.getLogger(__name__)


class SessionLifecycleMixin:
    """Mixin providing agent-wait, interrupt, resume and confirmation flows."""

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
        raw = os.getenv(name, str(default))
        try:
            return max(floor, int(raw))
        except (ValueError, TypeError):
            return default

    @classmethod
    def _resolve_hard_timeouts(cls) -> tuple[int, int]:
        hard = cls._coerce_env_int('APP_AGENT_HARD_TIMEOUT_SECONDS')
        cmd = cls._coerce_env_int('APP_AGENT_HARD_TIMEOUT_CMD_SECONDS')
        if hard > 0 and cmd > 0:
            cmd = max(hard, cmd)
        return hard, cmd

    @staticmethod
    def _active_timeout(
        controller: Any, hard_timeout: int, cmd_timeout: int,
    ) -> int:
        active = hard_timeout
        pending_action = getattr(controller, '_pending_action', None)
        if pending_action is None or cmd_timeout <= 0:
            return active
        with contextlib.suppress(Exception):
            from backend.ledger.action import CmdRunAction

            if isinstance(pending_action, CmdRunAction):
                active = cmd_timeout
        return active

    async def _wait_for_agent_idle(
        self, controller: Any, agent_task: asyncio.Task[Any] | None
    ) -> None:
        """Wait until agent is idle, handling confirmation prompts inline.

        Events are now processed directly in the EventStream delivery thread
        (no 3rd hop to the main loop), so the renderer state stays nearly in
        sync with the agent.  A brief yield after task completion is enough to
        let any in-flight deliveries finish.
        """
        # Disabled by default to avoid aborting long-running sessions.
        # Set APP_AGENT_HARD_TIMEOUT_SECONDS / APP_AGENT_HARD_TIMEOUT_CMD_SECONDS
        # to a positive value to re-enable limits.
        hard_timeout, cmd_timeout = self._resolve_hard_timeouts()
        start = time.monotonic()

        while True:
            renderer = cast(Any, self._renderer)

            # Drain queued events and render — this is the ONLY place
            # where Live.update() happens during agent execution.
            if renderer is not None:
                renderer.drain_events()
            state = controller.get_agent_state()

            if await self._handle_idle_or_confirmation(
                controller, renderer, state,
            ):
                break

            # Agent task finished — drain any remaining events, then break.
            if agent_task and agent_task.done():
                if renderer is not None:
                    await asyncio.sleep(0.05)
                    renderer.drain_events()
                break

            # Yield to the event loop.  wait_for_state_change will return
            # early when the delivery thread sets _state_event.
            if renderer is None:
                await asyncio.sleep(0.1)
            else:
                await renderer.wait_for_state_change(wait_timeout_sec=0.1)

            # Hard timeout — surface error and return to prompt instead of
            # hanging forever (e.g. LLM API unresponsive). Allow a longer
            # budget while a foreground command action is still pending.
            active_timeout = self._active_timeout(
                controller, hard_timeout, cmd_timeout,
            )
            if active_timeout > 0 and time.monotonic() - start > active_timeout:
                await self._handle_agent_hard_timeout(
                    renderer, agent_task, active_timeout,
                )
                break

    async def _handle_idle_or_confirmation(
        self, controller: Any, renderer: Any, state: AgentState,
    ) -> bool:
        """Return True when the wait loop should break out (agent is idle)."""
        if state in self._IDLE_AGENT_STATES:
            if renderer is not None:
                await self._drain_renderer_until_settled(renderer)
                state = controller.get_agent_state()
            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation(controller)
                return False
            return state in self._IDLE_AGENT_STATES
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            await self._handle_confirmation(controller)
        return False

    async def _handle_agent_hard_timeout(
        self,
        renderer: Any,
        agent_task: asyncio.Task[Any] | None,
        active_timeout: int,
    ) -> None:
        logger.warning('Agent wait exceeded %ds hard timeout', active_timeout)
        if renderer is not None:
            renderer.add_system_message(
                f'Agent timed out after {active_timeout} seconds. Returning to prompt.',
                title='⏱ Timeout',
            )
            renderer.drain_events()
        # Cancel the stale task so it does not linger into the next turn.
        if agent_task and not agent_task.done():
            agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await agent_task

    async def _drain_renderer_until_settled(
        self,
        renderer: Any,
        *,
        settle_delay: float = 0.03,
        max_passes: int = 3,
    ) -> None:
        """Drain queued CLI events until the delivery queue stays quiet briefly."""
        for _ in range(max_passes):
            renderer.drain_events()
            if getattr(renderer, 'pending_event_count', 0) == 0:
                await asyncio.sleep(settle_delay)
                renderer.drain_events()
                if getattr(renderer, 'pending_event_count', 0) == 0:
                    return
            else:
                await asyncio.sleep(settle_delay)

    # -- interrupt handler -------------------------------------------------

    async def _cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        """Cancel a running agent task and return to the prompt."""
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass

        # Hard kill underlying shells/processes
        with contextlib.suppress(Exception):
            from backend.execution.action_execution_server import (
                client as runtime_client,
            )

            if runtime_client is not None:
                await runtime_client.hard_kill()

        # Stop orchestrator cleanly
        if self._controller is not None:
            with contextlib.suppress(Exception):
                await self._controller.stop()

        self._reasoning.stop()
        if self._renderer is not None:
            self._renderer.add_system_message(
                'Interrupted. Ready for input.', title='grinta'
            )

    # -- session resume ----------------------------------------------------

    async def _resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller,
        create_status_callback,
        run_agent_until_done,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        """Resume a previous session by index or ID.

        Returns (controller, agent_task) on success, or None on failure.
        """
        bootstrap = self._validate_resume_bootstrap_state()
        if bootstrap is None:
            return None
        llm_registry, agent, conversation_stats = bootstrap

        resolved_id = self._resolve_resume_target(target, config)
        if resolved_id is None:
            return None

        runtime_bundle = self._setup_resume_runtime(
            config, llm_registry, agent, resolved_id,
        )
        if runtime_bundle is None:
            return None
        runtime, repo_directory, acquire_result, event_stream = runtime_bundle

        await self._wire_resume_runtime_state(
            config, runtime, agent, resolved_id, repo_directory,
            acquire_result, event_stream,
        )
        controller = self._build_resume_controller(
            agent, runtime, config, conversation_stats,
            create_controller, create_status_callback,
        )
        agent_task = asyncio.create_task(
            run_agent_until_done(controller, runtime, self._memory, end_states),
            name='grinta-agent-loop',
        )
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Session {resolved_id} resumed. Send a message to continue.',
                title='grinta',
            )
        return controller, agent_task

    def _validate_resume_bootstrap_state(
        self,
    ) -> tuple[Any, Any, Any] | None:
        llm_registry = self._llm_registry
        agent = self._agent
        conversation_stats = self._conversation_stats
        if llm_registry is None or agent is None or conversation_stats is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Resume failed: session bootstrap state is incomplete.',
                    title='error',
                )
            return None
        return llm_registry, agent, conversation_stats

    def _resolve_resume_target(
        self, target: str, config: AppConfig,
    ) -> str | None:
        from backend.cli.session_manager import resolve_session_id

        resolved_id, resolve_error = resolve_session_id(target, config)
        if resolve_error or resolved_id is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    resolve_error or f'No session matches: {target}', title='warning'
                )
            return None
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Resuming session: {resolved_id}', title='grinta'
            )
        return resolved_id

    def _setup_resume_runtime(
        self, config: AppConfig, llm_registry: Any, agent: Any, resolved_id: str,
    ) -> tuple[Any, Any, Any, Any] | None:
        from backend.core.bootstrap.main import _setup_runtime_for_controller

        try:
            runtime_state = _setup_runtime_for_controller(
                config,
                llm_registry,
                resolved_id,
                True,
                agent,
                None,
                inline_event_delivery=True,
            )
        except Exception as exc:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f'Resume failed: {exc}', title='error'
                )
            return None
        runtime = runtime_state[0]
        repo_directory = runtime_state[1]
        acquire_result = runtime_state[2]
        event_stream = runtime.event_stream
        if event_stream is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Resume failed: no event stream.', title='error'
                )
            return None
        return runtime, repo_directory, acquire_result, event_stream

    async def _wire_resume_runtime_state(
        self,
        config: AppConfig,
        runtime: Any,
        agent: Any,
        resolved_id: str,
        repo_directory: Any,
        acquire_result: Any,
        event_stream: Any,
    ) -> None:
        from backend.core.bootstrap.main import _setup_memory_and_mcp

        if self._acquire_result is not None:
            from backend.execution import runtime_orchestrator

            runtime_orchestrator.release(self._acquire_result)

        self._event_stream = event_stream
        self._runtime = runtime
        self._acquire_result = acquire_result

        memory = await _setup_memory_and_mcp(
            config, runtime, resolved_id, repo_directory, None, None, agent,
        )
        self._memory = memory
        mcp_status = getattr(agent, 'mcp_capability_status', None) or {}
        try:
            mcp_n = int(mcp_status.get('connected_client_count') or 0)
        except (TypeError, ValueError):
            mcp_n = 0
        self._hud.update_mcp_servers(mcp_n)

        # Subscribe renderer to the new event stream.
        if self._renderer is not None:
            renderer = cast(Any, self._renderer)
            renderer.reset_subscription()
            renderer.subscribe(event_stream, event_stream.sid)

    def _build_resume_controller(
        self,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        create_controller: Any,
        create_status_callback: Any,
    ) -> Any:
        controller, _ = create_controller(
            agent, runtime, config, conversation_stats,
        )
        runtime_for_controller = cast(Any, runtime)
        runtime_for_controller.controller = controller
        self._controller = controller

        early_cb = create_status_callback(controller)
        try:
            self._memory.status_callback = early_cb  # type: ignore[union-attr]
        except Exception:
            logger.debug('Could not set memory status callback', exc_info=True)
        return controller

    # -- confirmation handler ----------------------------------------------

    async def _handle_confirmation(self, controller) -> None:
        """Prompt user for Y/N on a pending action, then resume the engine."""
        pending = None
        try:
            pending = controller.get_pending_action()
        except Exception:
            logger.debug('get_pending_action() failed, trying fallback', exc_info=True)
            pending = getattr(controller, '_pending_action', None)

        if pending is not None:
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = render_confirmation(self._console, pending)
            else:
                approved = render_confirmation(self._console, pending)
        else:
            # Fallback: generic prompt if we can't get the pending action.
            from rich.prompt import Confirm

            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = Confirm.ask(
                        '[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]',
                        console=self._console,
                    )
            else:
                approved = Confirm.ask(
                    '[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]',
                    console=self._console,
                )

        action = build_confirmation_action(approved)
        if self._event_stream:
            self._event_stream.add_event(action, EventSource.USER)
