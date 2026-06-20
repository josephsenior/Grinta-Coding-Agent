"""Engine bootstrap pipeline for :class:`RunHelpersMixin`.

Owns the async chain that prepares a session for chat, sets up the
runtime bundle, and warms up MCP tools in the background:

- :func:`_engine_bootstrap` is the entry point that runs ``_bootstrap_status``
  updates between the three sub-steps.
- :func:`_bootstrap_init_session` (session components via
  ``_initialize_session_components``) and :func:`_bootstrap_setup_runtime`
  (runtime bundle + memory + renderer subscription) compose the cold
  path.
- :func:`_bootstrap_mcp_warmup` reports per-server progress while
  :func:`_setup_mcp_tools` is awaited; failures fall through to
  :func:`_handle_mcp_partial_state` to clear half-initialised state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import RunHelpersHost

logger = logging.getLogger(__name__)


async def _engine_bootstrap(
    host: 'RunHelpersHost',
    session: Any | None,
    renderer: Any,
    chat_ready_done: asyncio.Event,
    engine_init_done: asyncio.Event,
    engine_init_exc: list[BaseException | None],
) -> None:
    """Prepare chat first, then finish optional tool warmup in the background."""
    try:
        host._hud.update_agent_state('Starting')
        host._bootstrap_status('Initializing session…', session, renderer)

        init_ok = await _bootstrap_init_session(
            host,
            renderer,
            session,
            engine_init_exc,
        )
        if not init_ok:
            engine_init_exc.append(RuntimeError('Session initialization failed'))
            return

        host._bootstrap_status('Setting up runtime…', session, renderer)

        runtime_ok = await _bootstrap_setup_runtime(
            host,
            renderer,
            session,
            chat_ready_done,
            engine_init_exc,
        )
        if not runtime_ok:
            engine_init_exc.append(RuntimeError('Runtime setup failed'))
            return
        engine_init_done.set()

        agent = host._agent
        if agent is None or not agent.config.enable_mcp:
            host._bootstrap_status('Ready.', session, renderer, kind='system')
            return

        # MCP warmup — show per-server connection progress
        await _bootstrap_mcp_warmup(host, agent, session, renderer)
    finally:
        chat_ready_done.set()
        engine_init_done.set()


async def _bootstrap_init_session(
    host: 'RunHelpersHost',
    renderer: Any,
    session: Any | None,
    engine_init_exc: list[BaseException | None],
) -> bool:
    from backend.app.main import _initialize_session_components

    try:
        bootstrap_state = await asyncio.to_thread(
            _initialize_session_components,
            host._config,
            None,
        )
    except Exception as exc:
        host._handle_bootstrap_failure(exc, renderer, session, engine_init_exc)
        return False
    session_id = bootstrap_state[0]
    llm_registry = bootstrap_state[1]
    conversation_stats = bootstrap_state[2]
    config_ = bootstrap_state[3]
    agent = bootstrap_state[4]

    host._agent = agent
    host._llm_registry = llm_registry
    host._conversation_stats = conversation_stats
    host._config = config_
    host._hud.update_workspace(getattr(config_, 'project_root', None))
    host._bootstrap_session_id = session_id
    return True


async def _bootstrap_setup_runtime(
    host: 'RunHelpersHost',
    renderer: Any,
    session: Any | None,
    chat_ready_done: asyncio.Event,
    engine_init_exc: list[BaseException | None],
) -> bool:
    from backend.app.main import (
        _setup_memory,
        _setup_runtime_for_controller,
    )

    config_ = host._config
    agent = host._agent
    llm_registry = host._llm_registry
    session_id: str | None = getattr(host, '_bootstrap_session_id', None)
    try:
        runtime_state = await asyncio.to_thread(
            _setup_runtime_for_controller,
            config_,
            llm_registry,
            session_id,  # type: ignore[arg-type]
            True,
            agent,
            None,  # type: ignore[arg-type]
            inline_event_delivery=True,
        )
        runtime = runtime_state[0]
        repo_directory = runtime_state[1]
        acquire_result = runtime_state[2]

        event_stream = runtime.event_stream
        if event_stream is None:
            raise RuntimeError('Runtime did not produce an event stream.')

        host._event_stream = event_stream
        host._runtime = runtime
        host._acquire_result = acquire_result

        memory = await _setup_memory(
            config_,
            runtime,
            session_id,  # type: ignore[arg-type]
            repo_directory,
            None,
            None,
            agent,  # type: ignore[arg-type]
        )
        host._memory = memory

        renderer.subscribe(event_stream, event_stream.sid)
        host._announce_chat_ready(agent, session, renderer)
        host._hud.update_ledger('Healthy')
        host._invalidate_prompt_session(session)
        chat_ready_done.set()
        return True
    except Exception as exc:
        host._handle_bootstrap_failure(exc, renderer, session, engine_init_exc)
        return False


async def _bootstrap_mcp_warmup(
    host: 'RunHelpersHost',
    agent: Any,
    session: Any | None,
    renderer: Any,
) -> None:
    """Warm up MCP tools with per-server progress reporting."""
    import os

    from backend.app.main import _setup_mcp_tools

    verbose = os.environ.get('GRINTA_VERBOSE') == '1'
    server_count, server_names = _count_mcp_servers(agent)

    host._bootstrap_status(
        _format_warmup_msg(server_count, server_names, verbose), session, renderer
    )

    try:
        await _setup_mcp_tools(agent, host._runtime, host._memory)
    except Exception as exc:
        logger.warning('MCP warmup failed after chat became ready', exc_info=True)
        host._hud.update_mcp_servers(0)
        host._handle_mcp_partial_state(agent)
        host._bootstrap_status(
            f'MCP warmup failed: {exc}', session, renderer, kind='warning'
        )
        return

    host._update_mcp_count_from_agent(agent)
    host._bootstrap_status(
        _format_warmup_result(agent, server_count, verbose), session, renderer
    )


def _count_mcp_servers(agent: Any) -> tuple[int, list[str]]:
    server_count = 0
    server_names: list[str] = []
    try:
        mcp_config = getattr(agent.config, 'mcp', None) or getattr(
            agent.config, 'mcp_config', None
        )
        if mcp_config is not None:
            servers = getattr(mcp_config, 'servers', []) or []
            server_count = len(servers)
            server_names = [getattr(s, 'name', '?') for s in servers]
    except Exception:
        pass
    return server_count, server_names


def _format_warmup_msg(
    server_count: int, server_names: list[str], verbose: bool
) -> str:
    if server_count > 0:
        msg = f'MCP: connecting to {server_count} server(s)…'
        if verbose and server_names:
            msg += f' ({", ".join(server_names[:5])})'
        return msg
    return 'Loading MCP tools…'


def _format_warmup_result(agent: Any, server_count: int, verbose: bool) -> str:
    from backend.integrations.mcp.mcp_bootstrap_status import get_mcp_bootstrap_status

    status = get_mcp_bootstrap_status()
    client_count = int(status.get('connected_client_count', 0))
    errors = status.get('conversion_errors', []) or []

    if client_count > 0:
        detail = (
            f'{client_count}/{server_count} MCP server(s) connected.'
            if server_count > 0
            else f'{client_count} MCP server(s) connected.'
        )
        if verbose and errors:
            detail += f' {len(errors)} conversion error(s).'
    else:
        detail = 'MCP tools loaded.'
        if verbose and errors:
            detail += f' ({len(errors)} conversion errors)'
    return detail


def _bootstrap_status(
    host: 'RunHelpersHost',
    text: str,
    session: Any | None,
    renderer: Any,
    *,
    kind: str = 'system',
) -> None:
    """Update bootstrap status in footer (PT) or renderer (non-PT)."""
    if session is not None:
        host._set_footer_system_line(text, kind=kind)
    else:
        renderer.add_system_message(text, title=kind)


def _handle_mcp_partial_state(host: 'RunHelpersHost', agent: Any) -> None:
    """Handle partial MCP state after warmup failure.

    When MCP warmup fails after tools have been registered but clients
    weren't fully initialized, we need to clear the partial state to
    prevent the agent from using incomplete MCP tools.
    """
    try:
        mcp_config = getattr(agent.config, 'mcp', None) or getattr(
            agent.config, 'mcp_config', None
        )
        if mcp_config is not None:
            mcp_config.servers = []
        agent.mcp_capability_status = {
            'connected_client_count': 0,
            'partial_initialization': True,
            'error': 'warmup failed before full initialization',
        }
        logger.debug('Cleared partial MCP state after warmup failure')
    except Exception as exc:
        logger.warning('Failed to clear partial MCP state: %s', exc)


def _announce_chat_ready(
    host: 'RunHelpersHost',
    agent: Any,
    session: Any | None,
    renderer: Any,
) -> None:
    tip = '/help · /settings · /sessions'
    host._hud.update_agent_state('Ready')
    if agent.config.enable_mcp:
        msg = f'Chat ready. MCP tools warming in background. {tip}'
    else:
        host._hud.update_mcp_servers(0)
        msg = f'Ready. Describe a task or type {tip}.'
    if session is not None:
        host._set_footer_system_line(msg)
    else:
        renderer.add_system_message(msg, title='system')


def _update_mcp_count_from_agent(host: 'RunHelpersHost', agent: Any) -> None:
    from backend.integrations.mcp.native_backends import count_user_visible_mcp_servers

    config = getattr(host, '_config', None)
    if config is not None:
        host._hud.update_mcp_servers(count_user_visible_mcp_servers(config))
        return
    mcp_status = getattr(agent, 'mcp_capability_status', None) or {}
    try:
        mcp_n = int(mcp_status.get('connected_client_count') or 0)
    except (TypeError, ValueError):
        mcp_n = 0
    host._hud.update_mcp_servers(mcp_n)


def _handle_bootstrap_failure(
    host: 'RunHelpersHost',
    exc: BaseException,
    renderer: Any,
    session: Any | None,
    engine_init_exc: list[BaseException | None],
) -> None:
    engine_init_exc[0] = exc
    host._set_footer_system_line('')
    exc_name = type(exc).__name__
    msg: str
    if 'AuthenticationError' in exc_name or 'api_key' in str(exc).lower():
        msg = (
            'No API key or model configured.\n'
            'Run `grinta init` to configure a provider, '
            'or edit `settings.json` directly.\n'
            f'{exc}'
        )
        renderer.add_system_message(msg, title='error')
    else:
        msg = f'Initialization failed: {exc}'
        renderer.add_system_message(msg, title='error')
    # Print directly to stderr so the user sees the error even as
    # the REPL shuts down — renderer messages may not flush in time.
    import sys

    print(f'\n[Grinta] {msg}\n', file=sys.stderr)
    # Do NOT set self._running = False here.  Setting it kills the REPL
    # loop silently — the user never sees the error in the prompt area.
    # Instead leave _running True so the REPL stays alive and the user
    # can read the error message and fix config or type /exit.
