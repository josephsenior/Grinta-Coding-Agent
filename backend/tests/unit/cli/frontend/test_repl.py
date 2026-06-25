"""CLI frontend — repl."""

from backend.tests.unit.cli.frontend import _shared
from backend.tests.unit.cli.frontend._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.frontend._shared import (
    _build_command_completer,
    _build_help_markdown,
    _configure_redirected_streams,
    _console_output,
    _make_console,
    _parse_slash_command,
    _prompt_toolkit_available,
    _read_piped_stdin,
    _supports_prompt_session,
)


def test_show_grinta_splash_renders_logo_text() -> None:
    console = _make_console(width=120)
    show_grinta_splash(console)
    output = _console_output(console)

    # Non-TTY StringIO console: static frame with tagline + hint (see show_grinta_splash).
    assert 'AI coding agent' in output
    assert 'Describe a task' in output
    assert '/help' in output
    assert '/settings' in output
    assert '/quit' in output


def test_prompt_session_requires_tty_streams() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True
    piped_stream = MagicMock()
    piped_stream.isatty.return_value = False

    with patch('backend.cli.repl.slash_command_registry._prompt_toolkit_available', return_value=True):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is True
    assert _supports_prompt_session(piped_stream, interactive_stream) is False
    assert _supports_prompt_session(interactive_stream, piped_stream) is False
    assert _supports_prompt_session(interactive_stream, piped_stream) is False


def test_prompt_session_requires_prompt_toolkit() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True

    with patch(
        'backend.cli.repl.slash_command_registry._prompt_toolkit_available',
        return_value=False,
    ):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is False


def test_prompt_toolkit_available_returns_false_when_missing() -> None:
    original = sys.modules.get('prompt_toolkit')
    sys.modules.pop('prompt_toolkit', None)
    try:
        with patch.dict('sys.modules', {'prompt_toolkit': None}):
            assert _prompt_toolkit_available() is False
    finally:
        if original is not None:
            sys.modules['prompt_toolkit'] = original
        else:
            sys.modules.pop('prompt_toolkit', None)


def test_command_completer_suggests_matching_commands() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document('/s', cursor_position=len('/s')),
            None,
        )
    )

    assert {completion.text for completion in completions} >= {'/status', '/settings'}


def test_command_completer_suggests_ci_and_release_playbook_commands() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    ci_completions = list(
        completer.get_completions(
            Document('/c', cursor_position=len('/c')),
            None,
        )
    )
    release_completions = list(
        completer.get_completions(
            Document('/rel', cursor_position=len('/rel')),
            None,
        )
    )

    assert '/ci' in {completion.text for completion in ci_completions}
    assert '/release' in {completion.text for completion in release_completions}


def test_command_completer_suggests_autonomy_levels() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document('/autonomy b', cursor_position=len('/autonomy b')),
            None,
        )
    )

    assert [completion.text for completion in completions] == ['balanced']


def test_command_completer_suggests_resume_targets() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer(
        lambda: [
            ('1', '#1 Fix authentication bug'),
            ('session-123', 'Fix authentication bug'),
        ]
    )
    completions = list(
        completer.get_completions(
            Document('/resume s', cursor_position=len('/resume s')),
            None,
        )
    )

    assert [completion.text for completion in completions] == ['session-123']


def test_slash_command_parser_preserves_quoted_args_and_windows_paths() -> None:
    parsed = _parse_slash_command(r'/checkpoint "pre refactor" C:\Users\me\repo')

    assert parsed.name == '/checkpoint'
    assert parsed.args == ('pre refactor', r'C:\Users\me\repo')


def test_command_completer_suggests_diff_modes() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document('/diff --n', cursor_position=len('/diff --n')),
            None,
        )
    )

    assert [completion.text for completion in completions] == ['--name-only']


def test_configure_redirected_streams_uses_utf8_for_non_tty() -> None:
    redirected = MagicMock()
    redirected.isatty.return_value = False
    redirected.reconfigure = MagicMock()

    interactive = MagicMock()
    interactive.isatty.return_value = True
    interactive.reconfigure = MagicMock()

    _configure_redirected_streams(redirected, interactive, None)

    redirected.reconfigure.assert_called_once_with(encoding='utf-8', errors='replace')
    interactive.reconfigure.assert_not_called()


def test_read_piped_stdin_returns_none_for_tty() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch.object(sys, 'stdin', stdin):
        assert _read_piped_stdin() is None


def test_read_piped_stdin_reads_non_tty_once() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = 'queued task\n'

    with patch.object(sys, 'stdin', stdin):
        assert _read_piped_stdin() == 'queued task\n'


def test_help_markdown_is_scannable_without_adding_commands() -> None:
    markdown = _build_help_markdown()

    assert 'Send plain-language tasks at the prompt' in markdown
    assert '| Command | Purpose |' in markdown
    assert '/settings' in markdown
    assert 'Input shortcuts' in markdown


def test_help_markdown_lists_ci_and_release_playbook_commands() -> None:
    markdown = _build_help_markdown()

    assert '/ci' in markdown
    assert '/release' in markdown
