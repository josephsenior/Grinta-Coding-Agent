"""Slash-command registry, parsing, help, and prompt-toolkit helpers for the REPL.

This module is a thin re-export shim preserved for in-repo callers. The
real implementations live in the ``_slash_registry_*`` siblings:

* :mod:`backend.cli.repl.slash_registry_models` — data models
  (``SlashCommandSpec``, ``ParsedSlashCommand``, ``SlashCommandParseError``);
* :mod:`backend.cli.repl.slash_registry_commands` — command table,
  model list, autonomy level hints;
* :mod:`backend.cli.repl.slash_registry_parsing` — tokenization, alias
  resolution, and history file;
* :mod:`backend.cli.repl.slash_registry_help` — markdown and Rich
  help renderers;
* :mod:`backend.cli.repl.slash_registry_prompt` — tab-completion and
  key bindings;
* :mod:`backend.cli.repl.slash_registry_terminal` — terminal
  escape-sequence cleanup;
* :mod:`backend.cli.repl.slash_registry_clipboard` — OS clipboard
  helper.

The prompt-toolkit availability check and the TTY-stream guard stay in
this module so that the two existing test patches
(``backend.cli.repl.session._prompt_toolkit_available`` and
``backend.cli.repl.slash_command_registry._prompt_toolkit_available``)
continue to resolve the same module-level binding that the
``_supports_prompt_session`` lookup consults.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.cli.repl.slash_registry_clipboard import (
    copy_to_system_clipboard as _copy_to_system_clipboard,
)
from backend.cli.repl.slash_registry_commands import (
    _AUTONOMY_LEVEL_HINTS,
    _COMMAND_ALIASES,
    _COMMAND_NAMES,
    _KNOWN_MODELS,
    _PLAYBOOK_SLASH_COMMANDS,
    _SLASH_COMMANDS,
)
from backend.cli.repl.slash_registry_commands import (
    iter_command_completion_entries as _iter_command_completion_entries,
)
from backend.cli.repl.slash_registry_help import (
    HELP_INPUT_TIPS as _HELP_INPUT_TIPS,
)
from backend.cli.repl.slash_registry_help import (
    HELP_SECTION_COLLAPSE_THRESHOLD as _HELP_SECTION_COLLAPSE_THRESHOLD,
)
from backend.cli.repl.slash_registry_help import (
    HELP_SECTIONS_ORDER as _HELP_SECTIONS_ORDER,
)
from backend.cli.repl.slash_registry_help import (
    build_help_markdown as _build_help_markdown,
)
from backend.cli.repl.slash_registry_help import (
    build_help_table as _build_help_table,
)
from backend.cli.repl.slash_registry_help import (
    build_help_table_fallback as _build_help_table_fallback,
)
from backend.cli.repl.slash_registry_help import (
    closest_command_names as _closest_command_names,
)
from backend.cli.repl.slash_registry_help import (
    find_command_spec as _find_command_spec,
)
from backend.cli.repl.slash_registry_help import (
    help_for_specific_command as _help_for_specific_command,
)
from backend.cli.repl.slash_registry_help import (
    help_section_lines as _help_section_lines,
)
from backend.cli.repl.slash_registry_models import (
    ParsedSlashCommand,
    SlashCommandParseError,
    SlashCommandSpec,
)
from backend.cli.repl.slash_registry_parsing import (
    _HISTORY_DIR,
    _HISTORY_FILE,
)
from backend.cli.repl.slash_registry_parsing import (
    canonical_command_name as _canonical_command_name,
)
from backend.cli.repl.slash_registry_parsing import (
    ensure_history as _ensure_history,
)
from backend.cli.repl.slash_registry_parsing import (
    parse_slash_command as _parse_slash_command,
)
from backend.cli.repl.slash_registry_parsing import (
    split_command_words as _split_command_words,
)
from backend.cli.repl.slash_registry_prompt import (
    build_bindings as _build_bindings,
)
from backend.cli.repl.slash_registry_prompt import (
    build_command_completer as _build_command_completer,
)
from backend.cli.terminal_sanitize import (
    _CSI_OSC_DCS,
    _ORPHAN_BRACKET_CSI,
    _ORPHAN_PARAM_CHUNK_SINGLE,
    _ORPHAN_PARAM_CHUNK_STREAM,
)
from backend.cli.repl.slash_registry_terminal import (
    attach_prompt_buffer_csi_sanitizer as _attach_prompt_buffer_csi_sanitizer,
)
from backend.cli.repl.slash_registry_terminal import (
    looks_like_terminal_selection_noise as _looks_like_terminal_selection_noise,
)
from backend.cli.repl.slash_registry_terminal import (
    strip_leaked_terminal_artifacts as _strip_leaked_terminal_artifacts,
)

logger = logging.getLogger(__name__)


# Public-ish re-exports of underscore-prefixed names that callers have
# historically imported from this module. Defined here so the test patch
# ``patch('backend.cli.repl.slash_command_registry._prompt_toolkit_available', ...)``
# resolves to the same function that ``_supports_prompt_session`` looks
# up at call time (module-level name lookup in the caller's frame).


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
    'ParsedSlashCommand',
    'SlashCommandParseError',
    'SlashCommandSpec',
    '_AUTONOMY_LEVEL_HINTS',
    '_COMMAND_ALIASES',
    '_COMMAND_NAMES',
    '_CSI_OSC_DCS',
    '_HELP_INPUT_TIPS',
    '_HELP_SECTION_COLLAPSE_THRESHOLD',
    '_HELP_SECTIONS_ORDER',
    '_HISTORY_DIR',
    '_HISTORY_FILE',
    '_KNOWN_MODELS',
    '_ORPHAN_BRACKET_CSI',
    '_ORPHAN_PARAM_CHUNK_SINGLE',
    '_ORPHAN_PARAM_CHUNK_STREAM',
    '_PLAYBOOK_SLASH_COMMANDS',
    '_SLASH_COMMANDS',
    '_attach_prompt_buffer_csi_sanitizer',
    '_build_bindings',
    '_build_command_completer',
    '_build_help_markdown',
    '_build_help_table',
    '_build_help_table_fallback',
    '_canonical_command_name',
    '_closest_command_names',
    '_copy_to_system_clipboard',
    '_ensure_history',
    '_find_command_spec',
    '_help_for_specific_command',
    '_help_section_lines',
    '_iter_command_completion_entries',
    '_looks_like_terminal_selection_noise',
    '_parse_slash_command',
    '_prompt_toolkit_available',
    '_split_command_words',
    '_strip_leaked_terminal_artifacts',
    '_supports_prompt_session',
]
