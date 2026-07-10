"""Adapter that wires the MCP config bus to a running Runtime.

The TUI / controller / REPL each own a single in-process :class:`Runtime`.
This module is the bridge that:

* subscribes to the process-wide :class:`MCPConfigBus`;
* on every emission, calls :meth:`Runtime.reload_mcp` (when the runtime
  implements it) and re-runs :func:`add_mcp_tools_to_agent` so the
  agent's tool list stays in sync with the on-disk config;
* emits a small status :class:`StatusObservation` so the TUI sidebar
  shows the reload.

The runtime exposes :meth:`reload_mcp` and :meth:`close_mcp` so settings changes
can reconcile live MCP clients without restarting the session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from backend.execution.server.base import Runtime
    from backend.orchestration.agent import Agent

logger = logging.getLogger(__name__)


StatusEmitter = Callable[[str, dict[str, Any]], None]


class MCPReloadAdapter:
    """Bridge ``MCPConfigBus`` → live runtime + agent tool list.

    The adapter is intentionally small and dependency-light. It is
    installed by the TUI lifecycle bootstrap (see
    :mod:`backend.cli.tui.screen.lifecycle_bootstrap`) once the runtime
    + memory + agent are all up, and torn down when the screen
    unmounts.

    Parameters:
        runtime: The runtime whose MCP clients should be reconciled.
        agent: The active agent; its :meth:`set_mcp_tools` is the
            gateway to the LLM-visible tool list.
        memory: Used by :func:`add_mcp_tools_to_agent` to fetch
            playbook MCP servers.
        emit_status: Optional callback that receives a
            ``status_type`` and an ``extras`` dict. The TUI wires this
            to :func:`event_stream.add_event` with a
            :class:`StatusObservation`. When ``None``, status is
            only logged.

    """

    def __init__(
        self,
        *,
        runtime: Runtime,
        agent: Agent,
        memory: Any,
        emit_status: StatusEmitter | None = None,
    ) -> None:
        self._runtime = runtime
        self._agent = agent
        self._memory = memory
        self._emit_status = emit_status
        self._unsubscribe: Callable[[], None] | None = None
        self._bus_lock = asyncio.Lock()
        self._inflight: asyncio.Task[None] | None = None

    def install(self) -> Callable[[], None]:
        from backend.integrations.mcp.config_bus import get_mcp_config_bus

        bus = get_mcp_config_bus()

        def _on_change(change: Any) -> Awaitable[None] | None:
            return self._handle_change(change)

        self._unsubscribe = bus.subscribe(_on_change)
        if self._unsubscribe is None:
            return lambda: None
        return self._unsubscribe

    def close(self) -> None:
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
        self._unsubscribe = None
        inflight = self._inflight
        if inflight is not None and not inflight.done():
            inflight.cancel()
        self._inflight = None

    async def _handle_change(self, change: Any) -> None:
        async with self._bus_lock:
            existing = self._inflight
            if existing is not None and not existing.done():
                # Coalesce: let the in-flight task finish before we
                # start a new one. The next emission's diff will
                # already reflect the current state.
                try:
                    await existing
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            task = asyncio.create_task(
                self._reconcile(change), name='grinta-mcp-reload'
            )
            self._inflight = task

        try:
            await task
        finally:
            if self._inflight is task:
                self._inflight = None

    async def _reconcile(self, change: Any) -> None:
        diff = getattr(change, 'diff', None)
        old_cfg = getattr(change, 'old_config', None)
        new_cfg = getattr(change, 'new_config', None)
        master_changed = old_cfg is None or bool(
            getattr(old_cfg, 'enabled', False)
        ) != bool(getattr(new_cfg, 'enabled', False))
        if diff is None or (not diff.has_changes and not master_changed):
            return

        from backend.core.config import load_app_config

        cfg = load_app_config()
        runtime = self._runtime
        if hasattr(runtime, '_mcp_config'):
            runtime._mcp_config = cfg.mcp
        runtime_config = getattr(runtime, 'config', None)
        if runtime_config is not None:
            runtime_config.mcp = cfg.mcp

        # 1. Tell the runtime to drop / reconnect clients.
        reload_fn = getattr(self._runtime, 'reload_mcp', None)
        summary: dict[str, list[str]] = {}
        if callable(reload_fn):
            try:
                summary = await reload_fn()
            except Exception as exc:
                logger.error('Runtime reload_mcp failed: %s', exc, exc_info=True)
                self._status('mcp_reload_failed', {'error': str(exc)})
                return

        # 2. Rebuild the agent's tool list so the LLM sees the
        #    updated server / tool inventory.
        try:
            from backend.integrations.mcp import add_mcp_tools_to_agent

            _, tool_diff = await add_mcp_tools_to_agent(
                self._agent, self._runtime, self._memory
            )
        except Exception as exc:
            logger.error(
                'add_mcp_tools_to_agent failed during MCP reload: %s',
                exc,
                exc_info=True,
            )
            self._status(
                'mcp_reload_partial',
                {
                    'error': str(exc),
                    'summary': summary,
                },
            )
            return

        self._status(
            'mcp_reloaded',
            {
                'summary': summary,
                'tools': tool_diff,
            },
        )

    def _status(self, status_type: str, extras: dict[str, Any]) -> None:
        if self._emit_status is not None:
            try:
                self._emit_status(status_type, extras)
            except Exception:
                logger.debug('MCP reload status emit failed', exc_info=True)
        logger.info('MCP reload: %s extras=%s', status_type, extras)


__all__ = ['MCPReloadAdapter']
