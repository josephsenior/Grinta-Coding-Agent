"""Run-helpers mixin for :class:`backend.cli.repl.Repl`.

Contains the async bootstrap pipeline, prompt-session construction,
user-turn dispatch, and finalization helpers. Method bodies are extracted
into focused modules:

* :mod:`backend.cli.repl.run_helpers_prompt` — prompt-session and
  renderer construction.
* :mod:`backend.cli.repl.run_helpers_bootstrap` — engine bootstrap
  pipeline, MCP warmup, error reporting.
* :mod:`backend.cli.repl.run_helpers_dispatch` — input reading, slash
  command handling, user-turn dispatch, finalization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.cli.repl.run_helpers_bootstrap import (
    _announce_chat_ready,
    _bootstrap_init_session,
    _bootstrap_mcp_warmup,
    _bootstrap_setup_runtime,
    _bootstrap_status,
    _engine_bootstrap,
    _handle_bootstrap_failure,
    _handle_mcp_partial_state,
    _update_mcp_count_from_agent,
)
from backend.cli.repl.run_helpers_dispatch import (
    _cancel_task_silently,
    _close_event_stream,
    _discard_terminal_noise,
    _dispatch_user_turn,
    _ensure_controller_loop,
    _ensure_runtime_connected,
    _finalize_repl_run,
    _prepare_initial_action,
    _process_slash_command,
    _read_repl_input,
    _validate_engine_components_ready,
)
from backend.cli.repl.run_helpers_prompt import (
    _build_prompt_session,
    _build_renderer,
    _invalidate_prompt_session,
)

if TYPE_CHECKING:
    from backend.cli._typing import RunHelpersHost

logger = logging.getLogger(__name__)

__all__ = ['RunHelpersMixin']


def _create_prompt_session_from_host(host: 'RunHelpersHost') -> Any:
    return host._create_prompt_session()


def _handle_parsed_command_from_host(
    host: 'RunHelpersHost',
    parsed_command: Any,
) -> bool:
    return bool(host._handle_parsed_command(parsed_command))


async def _resume_session_from_host(
    host: 'RunHelpersHost',
    target: str,
    config: Any,
    create_controller: Any,
    create_status_callback: Any,
    run_agent_until_done: Any,
    end_states: list[Any],
) -> Any:
    return await host._resume_session(
        target,
        config,
        create_controller,
        create_status_callback,
        run_agent_until_done,
        end_states,
    )


class RunHelpersMixin:
    """Mixin providing the async run() pipeline helpers."""

    if TYPE_CHECKING:
        _config: Any
        _memory: Any
        _runtime: Any
        _agent: Any
        _llm_registry: Any
        _conversation_stats: Any
        _pt_session: Any
        _renderer: Any
        _console: Any
        _hud: Any
        _reasoning: Any
        _pending_resume: str | None
        _next_action: Any
        _last_user_message: str | None
        _prompt_ctrl_c_hint_shown: bool
        _running: bool

        def _create_prompt_session(self) -> Any: ...
        def _set_footer_system_line(self, text: str, *, kind: str = ...) -> None: ...
        async def _read_non_interactive_input(self) -> Any: ...
        def _handle_parsed_command(self, *args: Any, **kwargs: Any) -> Any: ...
        def _cancel_agent(self, *args: Any, **kwargs: Any) -> Any: ...
        def _resume_session(self, *args: Any, **kwargs: Any) -> Any: ...
        def _wait_for_agent_idle(self, *args: Any, **kwargs: Any) -> Any: ...
        def _sync_terminal_after_agent_turn(self, *args: Any, **kwargs: Any) -> Any: ...
        def _invalidate_pt(self) -> None: ...
        def _warn(self, msg: str) -> None: ...

    # -- prompt session ----------------------------------------------------

    def _build_prompt_session(self) -> Any | None:
        return _build_prompt_session(self)  # type: ignore[arg-type]

    def _build_renderer(self, session: Any | None, loop: Any) -> Any:
        return _build_renderer(self, session, loop)  # type: ignore[arg-type]

    def _invalidate_prompt_session(self, session: Any | None) -> None:
        _invalidate_prompt_session(session)

    # -- bootstrap pipeline -----------------------------------------------

    def _handle_bootstrap_failure(
        self,
        exc: BaseException,
        renderer: Any,
        session: Any | None,
        engine_init_exc: list[BaseException | None],
    ) -> None:
        _handle_bootstrap_failure(  # type: ignore[arg-type]
            self, exc, renderer, session, engine_init_exc
        )

    async def _engine_bootstrap(
        self,
        session: Any | None,
        renderer: Any,
        chat_ready_done: Any,
        engine_init_done: Any,
        engine_init_exc: list[BaseException | None],
    ) -> None:
        await _engine_bootstrap(  # type: ignore[arg-type]
            self,
            session,
            renderer,
            chat_ready_done,
            engine_init_done,
            engine_init_exc,
        )

    async def _bootstrap_mcp_warmup(
        self, agent: Any, session: Any | None, renderer: Any
    ) -> None:
        await _bootstrap_mcp_warmup(self, agent, session, renderer)  # type: ignore[arg-type]

    def _bootstrap_status(
        self,
        text: str,
        session: Any | None,
        renderer: Any,
        *,
        kind: str = 'system',
    ) -> None:
        _bootstrap_status(self, text, session, renderer, kind=kind)  # type: ignore[arg-type]

    def _handle_mcp_partial_state(self, agent: Any) -> None:
        _handle_mcp_partial_state(self, agent)  # type: ignore[arg-type]

    async def _bootstrap_init_session(
        self,
        renderer: Any,
        session: Any | None,
        engine_init_exc: list[BaseException | None],
    ) -> bool:
        return await _bootstrap_init_session(  # type: ignore[arg-type]
            self, renderer, session, engine_init_exc
        )

    async def _bootstrap_setup_runtime(
        self,
        renderer: Any,
        session: Any | None,
        chat_ready_done: Any,
        engine_init_exc: list[BaseException | None],
    ) -> bool:
        return await _bootstrap_setup_runtime(  # type: ignore[arg-type]
            self, renderer, session, chat_ready_done, engine_init_exc
        )

    def _announce_chat_ready(
        self, agent: Any, session: Any | None, renderer: Any
    ) -> None:
        _announce_chat_ready(self, agent, session, renderer)  # type: ignore[arg-type]

    def _update_mcp_count_from_agent(self, agent: Any) -> None:
        _update_mcp_count_from_agent(self, agent)  # type: ignore[arg-type]

    # -- input + dispatch --------------------------------------------------

    async def _read_repl_input(self, session: Any | None) -> str | None:
        return await _read_repl_input(self, session)  # type: ignore[arg-type]

    def _discard_terminal_noise(self, text: str) -> bool:
        return _discard_terminal_noise(self, text)  # type: ignore[arg-type]

    async def _process_slash_command(
        self,
        text: str,
        agent_task: Any,
        controller: Any,
        engine_init_done: Any,
        engine_init_exc: list[BaseException | None],
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[Any],
    ):
        return await _process_slash_command(  # type: ignore[arg-type]
            self,
            text,
            agent_task,
            controller,
            engine_init_done,
            engine_init_exc,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def _validate_engine_components_ready(self) -> bool:
        return _validate_engine_components_ready(self)  # type: ignore[arg-type]

    async def _dispatch_user_turn(
        self,
        text: str,
        controller: Any,
        agent_task: Any,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[Any],
        session: Any | None,
    ):
        return await _dispatch_user_turn(  # type: ignore[arg-type]
            self,
            text,
            controller,
            agent_task,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
            session,
        )

    async def _prepare_initial_action(self, text: str, renderer: Any) -> Any:
        return await _prepare_initial_action(self, text, renderer)  # type: ignore[arg-type]

    async def _ensure_runtime_connected(self, runtime: Any) -> None:
        await _ensure_runtime_connected(self, runtime)  # type: ignore[arg-type]

    async def _ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: Any,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: Any,
        conversation_stats: Any,
        memory: Any,
        end_states: list[Any],
    ):
        return await _ensure_controller_loop(  # type: ignore[arg-type]
            self,
            controller=controller,
            agent_task=agent_task,
            create_controller=create_controller,
            create_status_callback=create_status_callback,
            run_agent_until_done=run_agent_until_done,
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            memory=memory,
            end_states=end_states,
        )

    # -- finalization -----------------------------------------------------

    async def _finalize_repl_run(
        self,
        bootstrap_task: Any,
        agent_task: Any,
    ) -> None:
        await _finalize_repl_run(self, bootstrap_task, agent_task)  # type: ignore[arg-type]

    @staticmethod
    async def _cancel_task_silently(task: Any) -> None:
        await _cancel_task_silently(task)

    def _close_event_stream(self) -> None:
        _close_event_stream(self)  # type: ignore[arg-type]
