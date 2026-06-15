"""Prompt-session and renderer construction for :class:`RunHelpersMixin`.

Owns the three small helpers that wire the prompt-toolkit session, the
``CLIEventRenderer``, and the prompt-session invalidation hook used at
the end of every agent turn.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from backend.cli._typing import RunHelpersHost
from backend.cli.event_renderer import CLIEventRenderer

if TYPE_CHECKING:
    pass


def _build_prompt_session(host: RunHelpersHost) -> Any | None:
    import sys

    from backend.cli.repl.slash_command_registry import (
        _attach_prompt_buffer_csi_sanitizer,
        _supports_prompt_session,
    )

    session: Any | None = None
    if _supports_prompt_session(sys.stdin, sys.stdout):
        session = host._create_prompt_session()
        _attach_prompt_buffer_csi_sanitizer(session)
    host._pt_session = session
    return session


def _build_renderer(host: RunHelpersHost, session: Any | None, loop: Any) -> Any:
    config = host._config
    get_pt_session = (lambda: session) if session is not None else None
    renderer = CLIEventRenderer(
        host._console,
        host._hud,
        host._reasoning,
        loop=loop,
        max_budget=config.max_budget_per_task,
        get_prompt_session=get_pt_session,
        cli_tool_icons=config.cli_tool_icons,
    )
    host._renderer = renderer
    return renderer


def _invalidate_prompt_session(session: Any | None) -> None:
    if session is not None:
        with contextlib.suppress(Exception):
            session.app.invalidate()


def _create_prompt_session_from_host(host: RunHelpersHost) -> Any:
    return host._create_prompt_session()
