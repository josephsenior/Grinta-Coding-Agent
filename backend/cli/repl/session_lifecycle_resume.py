"""Session-resume helpers for :class:`SessionLifecycleMixin`.

Composed by ``_resume_session`` which calls each step in order:

1. ``_validate_resume_bootstrap_state`` — ensure LLM/agent/stats exist.
2. ``_resolve_resume_target`` — turn a user-supplied index/ID into a
   session ID via :func:`backend.cli.session.session_manager.resolve_session_id`.
3. ``_setup_resume_runtime`` — re-create the runtime bundle, releasing
   any partial state on failure.
4. ``_wire_resume_runtime_state`` — attach memory, MCP and renderer
   subscription to the new event stream.
5. ``_build_resume_controller`` — build a fresh controller and stash it
   back on the host.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from backend.core.config import AppConfig

if TYPE_CHECKING:
    from backend.cli._typing import SessionLifecycleHost

logger = logging.getLogger(__name__)


async def _resume_session(
    host: 'SessionLifecycleHost',
    target: str,
    config: AppConfig,
    create_controller: Any,
    create_status_callback: Any,
    run_agent_until_done: Any,
    end_states: list[Any],
) -> tuple[Any, Any] | None:
    """Resume a previous session by index or ID.

    Returns (controller, agent_task) on success, or None on failure.
    """
    self_obj = cast(Any, host)
    bootstrap = self_obj._validate_resume_bootstrap_state()
    if bootstrap is None:
        return None
    llm_registry, agent, conversation_stats = bootstrap

    resolved_id = self_obj._resolve_resume_target(target, config)
    if resolved_id is None:
        return None

    runtime_bundle = self_obj._setup_resume_runtime(
        config,
        llm_registry,
        agent,
        resolved_id,
    )
    if runtime_bundle is None:
        return None
    runtime, repo_directory, acquire_result, event_stream = runtime_bundle

    wire_ok = await self_obj._wire_resume_runtime_state(
        config,
        runtime,
        agent,
        resolved_id,
        repo_directory,
        acquire_result,
        event_stream,
    )
    if not wire_ok:
        return None
    controller = self_obj._build_resume_controller(
        agent,
        runtime,
        config,
        conversation_stats,
        create_controller,
        create_status_callback,
    )
    import asyncio

    agent_task = asyncio.create_task(
        run_agent_until_done(controller, runtime, host._memory, end_states),
        name='grinta-agent-loop',
    )
    if host._renderer is not None:
        host._renderer.add_system_message(
            f'Session {resolved_id} resumed. Send a message to continue.',
            title='grinta',
        )
    return controller, agent_task


def _validate_resume_bootstrap_state(
    host: 'SessionLifecycleHost',
) -> tuple[Any, Any, Any] | None:
    llm_registry = host._llm_registry
    agent = host._agent
    conversation_stats = host._conversation_stats
    if llm_registry is None or agent is None or conversation_stats is None:
        if host._renderer is not None:
            host._renderer.add_system_message(
                'Resume failed: session bootstrap state is incomplete.',
                title='error',
            )
        return None
    return llm_registry, agent, conversation_stats


def _resolve_resume_target(
    host: 'SessionLifecycleHost',
    target: str,
    config: AppConfig,
) -> str | None:
    from backend.cli.session.session_manager import resolve_session_id

    resolved_id, resolve_error = resolve_session_id(target, config)
    if resolve_error or resolved_id is None:
        if host._renderer is not None:
            host._renderer.add_system_message(
                resolve_error or f'No session matches: {target}', title='warning'
            )
        return None
    if host._renderer is not None:
        host._renderer.add_system_message(
            f'Resuming session: {resolved_id}', title='grinta'
        )
    return resolved_id


def _setup_resume_runtime(
    host: 'SessionLifecycleHost',
    config: AppConfig,
    llm_registry: Any,
    agent: Any,
    resolved_id: str,
) -> tuple[Any, Any, Any, Any] | None:
    from backend.app.main import _setup_runtime_for_controller

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
        if host._renderer is not None:
            host._renderer.add_system_message(f'Resume failed: {exc}', title='error')
        return None
    runtime = runtime_state[0]
    repo_directory = runtime_state[1]
    acquire_result = runtime_state[2]
    event_stream = runtime.event_stream
    if event_stream is None:
        # Clean up partially initialized runtime to prevent resource leaks.
        if acquire_result is not None:
            try:
                from backend.execution import runtime_orchestrator

                runtime_orchestrator.release(acquire_result)
            except Exception:
                logger.debug(
                    'Failed to release acquire_result during cleanup',
                    exc_info=True,
                )
        if host._renderer is not None:
            host._renderer.add_system_message(
                'Resume failed: no event stream.', title='error'
            )
        return None
    return runtime, repo_directory, acquire_result, event_stream


async def _wire_resume_runtime_state(
    host: 'SessionLifecycleHost',
    config: AppConfig,
    runtime: Any,
    agent: Any,
    resolved_id: str,
    repo_directory: Any,
    acquire_result: Any,
    event_stream: Any,
) -> bool:
    """Wire up runtime state for resume. Returns True on success, False on failure."""
    from backend.app.main import _setup_memory_and_mcp

    if host._acquire_result is not None:
        from backend.execution import runtime_orchestrator

        runtime_orchestrator.release(host._acquire_result)

    host._event_stream = event_stream
    host._runtime = runtime
    host._acquire_result = acquire_result

    try:
        memory = await _setup_memory_and_mcp(
            config,
            runtime,
            resolved_id,
            repo_directory,
            None,
            None,
            agent,
        )
    except Exception as exc:
        logger.error('Resume failed during memory/MCP setup: %s', exc, exc_info=True)
        if host._renderer is not None:
            host._renderer.add_system_message(
                f'Resume failed during memory/MCP setup: {exc}',
                title='error',
            )
        return False
    host._memory = memory
    from backend.integrations.mcp.native_backends import count_user_visible_mcp_servers

    host._hud.update_mcp_servers(count_user_visible_mcp_servers(host._config))

    # Subscribe renderer to the new event stream.
    if host._renderer is not None:
        renderer = cast(Any, host._renderer)
        renderer.reset_subscription()
        renderer.subscribe(event_stream, event_stream.sid)
    return True


def _build_resume_controller(
    host: 'SessionLifecycleHost',
    agent: Any,
    runtime: Any,
    config: AppConfig,
    conversation_stats: Any,
    create_controller: Any,
    create_status_callback: Any,
) -> Any:
    controller, _ = create_controller(
        agent,
        runtime,
        config,
        conversation_stats,
    )
    runtime_for_controller = cast(Any, runtime)
    runtime_for_controller.controller = controller
    host._controller = controller

    early_cb = create_status_callback(controller)
    try:
        host._memory.status_callback = early_cb  # type: ignore[union-attr]
    except Exception:
        logger.debug('Could not set memory status callback', exc_info=True)
    return controller
