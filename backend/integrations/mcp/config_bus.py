"""Process-wide pub/sub for MCP server configuration changes.

Background
----------
Mid-session mutations to ``settings.json`` (``mcp_config.servers``) used to
be persist-only: the file was rewritten but no consumer in the running
process ever re-ran tool discovery, reconnected clients, or refreshed the
agent's tool list. This module is the single source of truth that wires
the persistence layer to the runtime side.

The bus is intentionally tiny: a thread-safe registry of async or sync
callbacks, a snapshot of the most recent :class:`MCPConfig`, and a helper
that diffs the previous and next server list so subscribers (the
runtime, the TUI sidebar, the file watcher) can act on incremental
changes instead of paying a full reconnect cost on every keystroke.

It lives in :mod:`backend.integrations.mcp` rather than ``cli.settings``
so the runtime (which never imports the CLI) can subscribe without a
backwards dependency on the TUI module.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

if TYPE_CHECKING:
    from backend.core.config.mcp_config import MCPConfig, MCPServerConfig


logger = logging.getLogger(__name__)


def _server_identity(server: MCPServerConfig) -> tuple[str, str]:
    """Stable identity for diffing two server rows by name + type.

    ``name`` alone is the user-facing key, but a server can be edited from
    stdio→sse (or sse→shttp) while keeping the same name; such a change
    must trigger a reconnect, so we include the type as well.
    """
    return (getattr(server, 'name', ''), getattr(server, 'type', ''))


def _servers_by_identity(
    servers: Iterable[MCPServerConfig],
) -> dict[tuple[str, str], MCPServerConfig]:
    return {_server_identity(s): s for s in servers}


@dataclass(frozen=True)
class MCPServerDiff:
    """Incremental delta between two ``MCPConfig.servers`` lists.

    Attributes:
        added: Servers present in the new config but not the old.
        removed: Servers present in the old config but not the new.
        changed: Servers present in both whose fields differ. Maps the
            (name, type) identity to a tuple of ``(old, new)``.
        unchanged: Servers present in both with identical config.
        enabled_toggled: Servers whose ``enabled`` flag flipped (subset of
            ``changed`` when only the flag changed, otherwise empty so
            callers can still detect it via ``changed``).

    """

    added: list[MCPServerConfig] = field(default_factory=list)
    removed: list[MCPServerConfig] = field(default_factory=list)
    changed: dict[tuple[str, str], tuple[MCPServerConfig, MCPServerConfig]] = field(
        default_factory=dict
    )
    unchanged: list[MCPServerConfig] = field(default_factory=list)
    enabled_toggled: list[MCPServerConfig] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def diff_mcp_servers(
    old: Iterable[MCPServerConfig] | None,
    new: Iterable[MCPServerConfig] | None,
) -> MCPServerDiff:
    """Return the structural diff between two server lists.

    Servers with the same ``(name, type)`` identity are compared with
    :func:`MCPServerConfig.__eq__` so any field change (args, env, url,
    transport, api_key, usage_hint, enabled) registers as a change.
    """
    old_list = list(old or [])
    new_list = list(new or [])
    old_map = _servers_by_identity(old_list)
    new_map = _servers_by_identity(new_list)

    added_keys = set(new_map) - set(old_map)
    removed_keys = set(old_map) - set(new_map)
    shared_keys = set(old_map) & set(new_map)

    added = [new_map[k] for k in sorted(added_keys)]
    removed = [old_map[k] for k in sorted(removed_keys)]
    changed: dict[tuple[str, str], tuple[MCPServerConfig, MCPServerConfig]] = {}
    enabled_toggled: list[MCPServerConfig] = []
    unchanged: list[MCPServerConfig] = []

    for k in sorted(shared_keys):
        old_srv = old_map[k]
        new_srv = new_map[k]
        if old_srv == new_srv:
            unchanged.append(new_srv)
            continue
        changed[k] = (old_srv, new_srv)
        if old_srv.enabled != new_srv.enabled and (
            old_srv.command == new_srv.command
            and old_srv.args == new_srv.args
            and old_srv.url == new_srv.url
            and old_srv.api_key == new_srv.api_key
            and old_srv.env == new_srv.env
            and old_srv.transport == new_srv.transport
        ):
            enabled_toggled.append(new_srv)

    return MCPServerDiff(
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        enabled_toggled=enabled_toggled,
    )


@dataclass
class MCPConfigChange:
    """Payload delivered to bus subscribers on every config mutation.

    Attributes:
        old_config: The previous :class:`MCPConfig` snapshot (``None`` on
            the very first emit of the process).
        new_config: The freshly-loaded :class:`MCPConfig` snapshot.
        diff: Structural diff of the server list. May be empty when the
            file changed but ``mcp_config.servers`` did not (e.g. the user
            edited the model name only).
        source: Where the change originated — ``"mutation"`` for an
            in-process settings mutator, ``"file_watch"`` for an external
            edit detected by the watcher, ``"manual"`` for direct emits.
            Subscribers may use this to suppress feedback loops (e.g.
            avoid re-saving when source is ``"file_watch"``).

    """

    old_config: MCPConfig | None
    new_config: MCPConfig
    diff: MCPServerDiff
    source: str = 'mutation'


SubscriberCallback = Callable[
    [MCPConfigChange], Awaitable[None] | None
]


class MCPConfigBus:
    """Thread-safe pub/sub for MCP server configuration changes.

    The bus is a process-singleton. Subscribers register async or sync
    callbacks; :meth:`emit` invokes them serially in registration order.
    Callbacks are not awaited concurrently to keep the diff semantics
    linear (added → removed → changed) and to avoid the runtime racing
    its own reconnect.

    Failed callbacks log and continue — a single bad subscriber must
    never break the persistence write.
    """

    def __init__(self) -> None:
        self._subscribers: list[SubscriberCallback] = []
        self._lock = threading.Lock()
        self._snapshot: MCPConfig | None = None
        self._last_source: str | None = None

    # ------------------------------------------------------------------
    # Snapshot accessors
    # ------------------------------------------------------------------

    def snapshot(self) -> MCPConfig | None:
        """Return the most recent :class:`MCPConfig` emitted, or ``None``."""
        with self._lock:
            return self._snapshot

    def last_source(self) -> str | None:
        """Return the source string of the most recent :meth:`emit`."""
        with self._lock:
            return self._last_source

    def set_snapshot(
        self,
        config: MCPConfig | None,
        *,
        source: str = 'manual',
    ) -> None:
        """Install a snapshot without firing subscribers.

        Used at bootstrap to seed the bus with the on-disk config so
        the first :meth:`emit` can compute a meaningful diff instead of
        treating every server as ``added``.
        """
        with self._lock:
            self._snapshot = config
            self._last_source = source

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, callback: SubscriberCallback) -> Callable[[], None]:
        """Register ``callback``; returns an unsubscribe callable."""
        with self._lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return _unsubscribe

    def clear(self) -> None:
        """Remove every subscriber. Tests use this between cases."""
        with self._lock:
            self._subscribers.clear()

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def emit(
        self,
        new_config: MCPConfig,
        *,
        source: str = 'mutation',
    ) -> MCPConfigChange:
        """Compute a diff and dispatch it to all subscribers.

        Returns the change payload so callers can log it or act
        synchronously before kicking off the async dispatch.
        """
        with self._lock:
            old = self._snapshot
            self._snapshot = new_config
            self._last_source = source
            subscribers = list(self._subscribers)

        change = MCPConfigChange(
            old_config=old,
            new_config=new_config,
            diff=diff_mcp_servers(
                old.servers if old is not None else None,
                new_config.servers,
            ),
            source=source,
        )

        if not subscribers:
            return change

        for cb in subscribers:
            try:
                result = cb(change)
            except Exception:
                logger.exception(
                    'MCPConfigBus subscriber raised during emit (source=%s)',
                    source,
                )
                continue
            if result is None:
                continue
            # Async callbacks: fire-and-forget so the writer of the
            # config never blocks on slow reconnects. Errors are logged
            # by the awaited coroutine below.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No loop (sync unit tests): run inline. Subscribers that
                # returned a coroutine without a loop are the test's
                # problem — they should ``await`` directly.
                try:
                    asyncio.run(result)
                except Exception:
                    logger.exception(
                        'MCPConfigBus async subscriber failed (no running loop)'
                    )
                continue
            loop.create_task(_safe_await(result, source))

        return change

    # ------------------------------------------------------------------
    # Introspection (mostly for tests / status panels)
    # ------------------------------------------------------------------

    def has_changes_since(
        self, prior: MCPConfig | None
    ) -> bool:
        """Return True when the current snapshot differs from ``prior``."""
        with self._lock:
            current = self._snapshot
        if current is None and prior is None:
            return False
        if current is None or prior is None:
            return True
        return diff_mcp_servers(prior.servers, current.servers).has_changes


async def _safe_await(awaitable: Awaitable[Any], source: str) -> None:
    try:
        await awaitable
    except Exception:
        logger.exception(
            'MCPConfigBus async subscriber failed (source=%s)', source
        )


# Process-singleton accessor. Tests can ``bus.clear()`` / ``bus.set_snapshot(...)``
# to reset between cases.
_bus: MCPConfigBus = MCPConfigBus()


def get_mcp_config_bus() -> MCPConfigBus:
    """Return the process-wide :class:`MCPConfigBus`."""
    return _bus


def reset_mcp_config_bus() -> None:
    """Drop subscribers and snapshot. Test-only."""
    _bus.clear()
    _bus.set_snapshot(None)


__all__ = [
    'MCPConfigBus',
    'MCPConfigChange',
    'MCPServerDiff',
    'diff_mcp_servers',
    'get_mcp_config_bus',
    'reset_mcp_config_bus',
]
