"""Startup-time capability matrix for Forge runtimes.

:class:`RuntimeCapabilities` is a frozen snapshot of what a runtime can
(and cannot) do, populated once during ``connect()`` and queryable by
downstream code.  This replaces scattered ``sys.platform`` / ``shutil.which``
checks with a single structured source of truth.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Immutable snapshot of capabilities available in the current runtime.

    Populated once during startup and attached to the :class:`Runtime`
    instance so that any code with a runtime reference can inspect
    capabilities deterministically.
    """

    # -- platform -----------------------------------------------------------
    platform: str = ""
    """``sys.platform`` at snapshot time (e.g. ``'win32'``, ``'linux'``)."""

    is_windows: bool = False
    """True when running on Windows (any variant)."""

    # -- tools --------------------------------------------------------------
    has_git: bool = False
    has_tmux: bool = False
    has_bash: bool = False

    # -- feature flags ------------------------------------------------------
    can_browse: bool = False
    """True when browser interactions are enabled for this runtime."""

    can_mcp: bool = False
    """True when MCP stdio servers can be spawned (not Windows currently)."""

    can_copy_from_runtime: bool = True
    """True when ``copy_from`` is available (always True for local runtime)."""

    # -- summary ------------------------------------------------------------
    missing_tools: tuple[str, ...] = ()
    """Names of tools that are expected but missing."""


def detect_capabilities(
    *,
    enable_browser: bool = False,
    mcp_config: object | None = None,
) -> RuntimeCapabilities:
    """Probe the host environment and return a frozen capability snapshot.

    This function is intentionally *fast* — it only calls ``shutil.which``
    and checks a few env-vars.  It should be called once during
    ``Runtime.connect()`` and the result stored on ``self.capabilities``.
    """
    platform = sys.platform
    is_windows = platform == "win32"

    has_git = shutil.which("git") is not None
    has_tmux = shutil.which("tmux") is not None
    has_bash = shutil.which("bash") is not None

    # Browser interactions are provided via external tooling (e.g., MCP).
    # Do not depend on any specific browser automation library being installed.
    can_browse = bool(enable_browser)

    # MCP can be supported either via HTTP/SSE servers (cross-platform) or via
    # stdio servers (requires spawning npx/uvx or other commands).
    shutil.which("npx") is not None
    shutil.which("uvx") is not None

    has_http_mcp = False
    try:
        servers = getattr(mcp_config, "servers", None)
        if servers:
            has_http_mcp = any(
                getattr(s, "type", None) in {"sse", "shttp"} for s in servers
            )
    except Exception:
        has_http_mcp = False

    # Windows stdio MCP is not currently supported; only allow MCP there when
    # an HTTP-based MCP server is configured.
    can_mcp = has_http_mcp or (not is_windows)

    # Collect missing tools for diagnostic logging
    expected = {"git": has_git}
    if not is_windows:
        expected["tmux"] = has_tmux
        expected["bash"] = has_bash
    missing = tuple(name for name, found in expected.items() if not found)

    return RuntimeCapabilities(
        platform=platform,
        is_windows=is_windows,
        has_git=has_git,
        has_tmux=has_tmux,
        has_bash=has_bash,
        can_browse=can_browse,
        can_mcp=can_mcp,
        can_copy_from_runtime=True,
        missing_tools=missing,
    )
