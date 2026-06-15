"""Prompt-toolkit completer and key bindings for the interactive REPL.

These two pieces are the prompt-toolkit integration surface:

* :func:`build_command_completer` — tab-completion for ``/command``,
  ``/autonomy <level>``, ``/model <id>``, ``/help <name>``, ``/diff
  <flag>``, and ``/resume <id>`` (using a session loader for recents);
* :func:`build_bindings` — Alt+Enter (insert newline) and Ctrl+R
  (transcript search dialog).

The prompt-toolkit availability check (``_prompt_toolkit_available``)
and the TTY-stream guard (``_supports_prompt_session``) are kept in
:mod:`backend.cli.repl.slash_command_registry` because tests patch
them in that module's namespace and the resolver follows the same
module lookup.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.cli.repl.slash_registry_commands import (
    _AUTONOMY_LEVEL_HINTS,
    _KNOWN_MODELS,
    iter_command_completion_entries,
)
from backend.cli.repl.slash_registry_parsing import canonical_command_name


def build_command_completer(
    load_session_suggestions: Callable[[], list[tuple[str, str]]] | None = None,
) -> Any:
    """Create the prompt-toolkit completer used by the interactive REPL."""
    from prompt_toolkit.completion import Completer, Completion

    session_loader = load_session_suggestions or (lambda: [])

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # type: ignore[override]
            del complete_event
            text_before_cursor = document.text_before_cursor.lstrip()
            if not text_before_cursor.startswith('/'):
                return

            has_trailing_space = document.text_before_cursor.endswith(' ')
            parts = text_before_cursor.split()
            if not parts:
                return

            command_token = parts[0].lower()
            if len(parts) == 1 and not has_trailing_space:
                prefix = command_token
                for name, description in iter_command_completion_entries():
                    if name.startswith(prefix):
                        yield Completion(
                            name,
                            start_position=-len(prefix),
                            display_meta=description,
                        )
                return

            canonical_command = canonical_command_name(command_token)
            argument_prefix = '' if has_trailing_space or len(parts) < 2 else parts[1]

            if canonical_command == '/autonomy':
                lowered_prefix = argument_prefix.lower()
                for level, description in _AUTONOMY_LEVEL_HINTS.items():
                    if level.startswith(lowered_prefix):
                        yield Completion(
                            level,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/model':
                lowered_prefix = argument_prefix.lower()
                for model_id, provider in _KNOWN_MODELS:
                    if lowered_prefix and not model_id.startswith(lowered_prefix):
                        continue
                    yield Completion(
                        model_id,
                        start_position=-len(argument_prefix),
                        display_meta=provider,
                    )
                return

            if canonical_command == '/help':
                lowered_prefix = argument_prefix.lower()
                for name, description in iter_command_completion_entries():
                    if name.startswith(lowered_prefix):
                        yield Completion(
                            name,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/diff':
                lowered_prefix = argument_prefix.lower()
                for option, description in (
                    ('--stat', 'Summary by file'),
                    ('--name-only', 'Changed file names'),
                    ('--patch', 'Full patch'),
                ):
                    if option.startswith(lowered_prefix):
                        yield Completion(
                            option,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/resume':
                lowered_prefix = argument_prefix.lower()
                seen: set[str] = set()
                for candidate, description in session_loader():
                    if candidate in seen:
                        continue
                    if lowered_prefix and not candidate.lower().startswith(
                        lowered_prefix
                    ):
                        continue
                    seen.add(candidate)
                    yield Completion(
                        candidate,
                        start_position=-len(argument_prefix),
                        display_meta=description,
                    )

    return SlashCommandCompleter()


def build_bindings() -> Any:
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        """Alt+Enter inserts a newline (multi-line input)."""
        event.current_buffer.insert_text('\n')

    @kb.add(Keys.ControlR, eager=True)
    def _transcript_search(event):
        """Ctrl+R opens a transcript search prompt."""
        from prompt_toolkit.shortcuts import input_dialog
        from prompt_toolkit.styles import Style

        app = event.app

        async def _do_search():
            try:
                result = await input_dialog(
                    title='Search Transcript',
                    text='Enter search query:',
                    style=Style.from_dict(
                        {
                            'dialog': 'bg:#1b233a',
                            'dialog.body': 'bg:#0f1525 #e9e9e9',
                            'dialog.title': 'bg:#0f1525 #91abec bold',
                            'dialog.body text-area': 'bg:#0a0e1b #e9e9e9',
                        }
                    ),
                ).run_async()
                if result and result.strip():
                    # Insert the search command into the buffer
                    app.current_buffer.text = f'/search {result.strip()}'
                    app.current_buffer.validate_and_handle()
            except Exception:
                pass

        app.create_background_task(_do_search())

    return kb
