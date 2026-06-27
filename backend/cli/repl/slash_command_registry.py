"""Backward-compat re-export shim for the slash-command registry.

New code should import from the focused submodules (e.g.
``backend.cli.repl.slash_registry_commands``). This module exists only
to keep the test patch paths
``patch('backend.cli.repl.slash_command_registry._prompt_toolkit_available', ...)``
and
``patch('backend.cli.repl.slash_command_registry._copy_to_system_clipboard', ...)``
working. When those tests are migrated, this shim can be deleted.
"""

from __future__ import annotations

from typing import Any

from backend.cli.repl.slash_registry_clipboard import (
    copy_to_system_clipboard as _copy_to_system_clipboard,
)


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def _supports_prompt_session(input_stream: Any, output_stream: Any) -> bool:
    """Use prompt_toolkit only when both streams are attached to a TTY."""
    input_is_tty = bool(getattr(input_stream, 'isatty', lambda: False)())
    output_is_tty = bool(getattr(output_stream, 'isatty', lambda: False)())
    return input_is_tty and output_is_tty and _prompt_toolkit_available()


__all__ = [
    '_copy_to_system_clipboard',
    '_prompt_toolkit_available',
    '_supports_prompt_session',
]
