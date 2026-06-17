"""CLI frontend — diff."""

from backend.tests.unit.cli.frontend import _shared
from backend.tests.unit.cli.frontend._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)


from backend.tests.unit.cli.frontend._shared import (
    _console_output,
    _make_config,
    _make_console,
)


def test_diff_panel_new_file() -> None:
    """DiffPanel should show creation info for new files."""
    obs = MagicMock()
    obs.path = 'src/main.py'
    obs.tool_result = {'operation': 'create_file', 'ok': True}
    obs.outcome = 'created'
    obs.old_content = None
    obs.new_content = "print('hello')\nprint('world')\n"
    obs.content = 'File created'

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'Created' in output
    assert 'src/main.py' in output
    assert '+2 lines' in output
    assert "print('hello')" in output
    assert "print('world')" in output


def test_diff_panel_new_xml_file_shows_plain_preview() -> None:
    """DiffPanel should render new XML file content as plain text preview."""
    obs = MagicMock()
    obs.path = 'src/config.xml'
    obs.tool_result = {'operation': 'create_file', 'ok': True}
    obs.outcome = 'created'
    obs.old_content = None
    obs.new_content = '<root>\n  <item>value</item>\n</root>\n'
    obs.content = 'File created'

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert '<root>' in output
    assert '<item>value</item>' in output
    assert '```xml' not in output


def test_diff_panel_existing_file_with_groups() -> None:
    """DiffPanel should render edit groups for existing file edits."""
    obs = MagicMock()
    obs.path = 'README.md'
    obs.tool_result = {'operation': 'replace_string', 'ok': True}
    obs.outcome = 'edited'
    obs.old_content = 'old'
    obs.get_edit_groups.return_value = [
        {
            'before_edits': ['- old line 1'],
            'after_edits': ['+ new line 1', '+ new line 2'],
        }
    ]

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'Edited' in output
    assert 'README.md' in output
    assert '+2 lines' in output
    assert '-1 lines' in output


def test_diff_panel_shows_files_badge_title_when_requested() -> None:
    obs = MagicMock()
    obs.path = 'src/main.py'
    obs.tool_result = {'operation': 'replace_string', 'ok': True}
    obs.outcome = 'edited'
    obs.old_content = 'old'
    obs.get_edit_groups.return_value = [
        {
            'before_edits': ['-print("old")'],
            'after_edits': ['+print("new")'],
        }
    ]

    panel = DiffPanel(obs, badge_label='file_edit')
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'Files' in output
    assert 'main.py' in output


def test_diff_panel_extracts_diff_preview_block() -> None:
    obs = MagicMock()
    obs.path = 'README.md'
    obs.tool_result = {'operation': 'replace_string', 'ok': True}
    obs.outcome = 'edited'
    obs.old_content = 'old'
    obs.diff = None
    obs.get_edit_groups.return_value = []
    obs.visualize_diff.side_effect = RuntimeError('no old/new content')
    obs.content = (
        'updated\n\n<DIFF_PREVIEW>\n'
        '--- README.md\n+++ README.md\n@@ -1 +1 @@\n-old\n+new\n'
        '</DIFF_PREVIEW>'
    )

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'README.md' in output
    assert '+new' in output


def test_diff_command_uses_configured_project_root(tmp_path: Path) -> None:
    config = _make_config()
    config.project_root = str(tmp_path)
    repl = Repl(config, Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)
    completed = subprocess.CompletedProcess(
        args=['git', 'diff'], returncode=0, stdout='src/app.py\n', stderr=''
    )

    with patch(
        'backend.cli.repl.slash_commands_mixin.subprocess.run',
        return_value=completed,
    ) as run_git:
        result = repl.handle_command('/diff --name-only "src/app file.py"')

    assert result is True
    run_git.assert_called_once()
    assert run_git.call_args.args[0] == [
        'git',
        'diff',
        '--name-only',
        '--',
        'src/app file.py',
    ]
    assert run_git.call_args.kwargs['cwd'] == tmp_path.resolve()
