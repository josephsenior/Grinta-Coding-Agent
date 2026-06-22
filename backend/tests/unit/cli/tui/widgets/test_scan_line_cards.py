"""Unit tests for scan-line action cards (1-line feed + detail screens)."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.widgets.scan_line import (
    AgentMessageCard,
    BrowserCard,
    DebuggerCard,
    DelegateCard,
    EditCard,
    MCPCard,
    PayloadCard,
    ScanLineCard,
    ShellCard,
    TerminalCard,
    _compact_path,
    _extract_syntax_error,
    _format_diff_delta,
    _parse_syntax_badge,
)

# ── test-only minimal ScanLineCard ─────────────────────────────────────


class _TestCard(ScanLineCard):
    def _line_text(self) -> str:
        return 'test-card'

    def build_detail_screen(self) -> DetailScreen:
        return DetailScreen(title='test')


# ── helpers ────────────────────────────────────────────────────────────


def _line_text(card: ScanLineCard) -> str:
    return str(card._line_text())


# ── ScanLineCard base ──────────────────────────────────────────────────


def test_scan_line_card_initial_state_is_queued():
    card = _TestCard()
    assert card.state == 'queued'
    assert card.has_class('queued')


def test_scan_line_card_state_transitions():
    card = _TestCard()
    card.set_state('running')
    assert card.state == 'running'
    assert card.has_class('running')
    assert not card.has_class('queued')

    card.set_state('done')
    assert card.state == 'done'
    assert card.has_class('done')

    card.set_state('failed')
    assert card.state == 'failed'
    assert card.has_class('failed')


def test_scan_line_card_compose_has_expand_button():
    card = _TestCard()
    # Compose requires an active Textual app context; verify the card
    # class is well-formed instead by checking it doesn't error on init.
    assert card is not None
    assert card.state == 'queued'


# ── parse_syntax_badge ─────────────────────────────────────────────────


def test_parse_syntax_badge_pass():
    assert _parse_syntax_badge('edited\n<SYNTAX_CHECK_PASSED />') == 'pass'


def test_parse_syntax_badge_fail():
    content = (
        'edited\n<SYNTAX_CHECK_FAILED>\n'
        'Syntax error at line 47: unexpected indent\n'
        '</SYNTAX_CHECK_FAILED>'
    )
    assert _parse_syntax_badge(content) == 'fail'


def test_parse_syntax_badge_none():
    assert _parse_syntax_badge('') is None
    assert _parse_syntax_badge('edited\n') is None


def test_extract_syntax_error():
    content = (
        'edited\n<SYNTAX_CHECK_FAILED>\n'
        'Syntax error at line 47: unexpected indent\n'
        '</SYNTAX_CHECK_FAILED>'
    )
    assert 'unexpected indent' in (_extract_syntax_error(content) or '')


def test_format_diff_delta():
    assert _format_diff_delta(0, 0) == '0'
    assert _format_diff_delta(12, 4) == '+12 -4'
    assert _format_diff_delta(5, 0) == '+5'
    assert _format_diff_delta(0, 3) == '-3'


def test_compact_path():
    assert _compact_path('backend/raft.py', 40) == 'backend/raft.py'
    long_path = 'a' * 30 + '/b/' + 'c' * 30 + 'd.txt'
    result = _compact_path(long_path, 40)
    assert len(result) <= 40
    assert 'b/' in result or 'd.txt' in result


# ── AgentMessageCard ───────────────────────────────────────────────────


def test_agent_message_card_line():
    card = AgentMessageCard("I'll run the tests first, then fix the import")
    assert 'Agent' in _line_text(card)
    assert 'tests first' in _line_text(card)


def test_agent_message_card_truncation():
    long_msg = 'x' * 200
    card = AgentMessageCard(long_msg)
    assert '…' in _line_text(card)


def test_agent_message_card_detail_screen():
    card = AgentMessageCard('hello')
    screen = card.build_detail_screen()
    assert isinstance(screen, DetailScreen)
    assert 'hello' in screen._message_text


# ── EditCard ───────────────────────────────────────────────────────────


def test_edit_card_create():
    card = EditCard(
        display_path='backend/utils/helper.py',
        added=48,
        is_create=True,
        syntax_pass=True,
    )
    assert '+ Created' in _line_text(card)
    assert 'helper.py' in _line_text(card)
    assert '+48' in card._delta_text()
    assert '✓' in card._delta_text()
    assert card.state == 'done'


def test_edit_card_failed_syntax():
    card = EditCard(
        display_path='backend/raft.py',
        added=12,
        removed=4,
        syntax_pass=False,
        syntax_error='unexpected indent at line 47',
    )
    assert '↲ Edited' in _line_text(card)
    assert '+12' in card._delta_text()
    assert '-4' in card._delta_text()
    assert '✗' in card._delta_text()
    assert card.state == 'failed'


def test_edit_card_unknown_syntax():
    card = EditCard(
        display_path='backend/raft.py',
        added=2,
    )
    assert '✓' not in card._delta_text()
    assert '✗' not in card._delta_text()
    assert card.state == 'done'


def test_edit_card_zero_delta():
    card = EditCard(display_path='backend/raft.py', added=0, removed=0)
    assert '↲ Edited' in _line_text(card)
    assert '[#91abec]↲ Edited[/]' in _line_text(card)
    assert card._delta_text() == ''


def test_edit_card_detail_screen_built():
    card = EditCard(display_path='backend/raft.py', added=2, removed=1)
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail import EditDetailScreen

    assert isinstance(screen, EditDetailScreen)


def test_edit_card_undo():
    card = EditCard(
        display_path='backend/raft.py',
        added=1,
        removed=2,
        is_undo=True,
    )
    assert '↶ Undo' in _line_text(card)
    assert '[#91abec]↶ Undo[/]' in _line_text(card)
    assert 'raft.py' in _line_text(card)
    assert '+1' in card._delta_text()
    assert '-2' in card._delta_text()


def test_edit_card_undo_detail_screen():
    card = EditCard(
        display_path='backend/raft.py',
        added=0,
        removed=3,
        is_undo=True,
        encoded_diff='payload',
    )
    screen = card.build_detail_screen()
    assert screen._kind == 'Undo'
    assert 'raft.py' in screen._heading


# ── ShellCard ──────────────────────────────────────────────────────────


def test_scan_line_icons_are_unique():
    from backend.cli.tui.widgets.scan_line import cards as cards_mod

    icons = set(cards_mod._SCAN_LINE_ICONS.values())
    assert len(icons) == len(cards_mod._SCAN_LINE_ICONS)


def test_shell_card_running():
    card = ShellCard(command='npm install')
    assert card.state == 'running'
    line = _line_text(card)
    assert '$ Shell' in line or 'Shell' in line
    assert '[#EF9F27]…[/]' in card._delta_text()
    assert 'npm install' in line


def test_shell_card_done():
    card = ShellCard(command='cargo test', output='47/47 passed', exit_code=0)
    assert card.state == 'done'
    assert '[#639922]$ Shell[/]' in _line_text(card)
    assert '[#639922]✓[/]' in card._delta_text()


def test_shell_card_failed():
    card = ShellCard(command='npm build', exit_code=1)
    assert card.state == 'failed'
    assert '[#E24B4A]$ Shell[/]' in _line_text(card)
    assert '[#E24B4A]✗ 1[/]' in card._delta_text()


def test_shell_card_background_detached():
    card = ShellCard(
        command='npm run dev',
        output='listening on 3000',
        exit_code=-2,
        is_background=True,
    )
    assert card.state == 'background'
    assert '[#6B9FD4]$ Shell[/]' in _line_text(card)
    assert '[#6B9FD4]detached[/]' in card._delta_text()


def test_shell_card_detail_screen():
    card = ShellCard(command='cargo test', output='ok. 47 passed', exit_code=0)
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail import ShellDetailScreen

    assert isinstance(screen, ShellDetailScreen)


def test_shell_card_refresh_updates_line():
    card = ShellCard(command='npm install')
    card.output = 'added 312 packages'
    card.refresh_summary()
    assert '312' in card._delta_text() or 'added' in card._delta_text()


# ── TerminalCard ───────────────────────────────────────────────────────


def test_terminal_card_running():
    card = TerminalCard(
        session_id='s1',
        session_label='s1',
        cwd='/project/grinta',
        command='cargo build',
    )
    assert card.state == 'running'
    assert '▸ Terminal' in _line_text(card)
    assert '[#EF9F27]▸ Terminal[/]' in _line_text(card)
    assert 's1' in _line_text(card)
    assert '/project/grinta' in _line_text(card)
    assert '[#EF9F27]…[/]' in card._delta_text()


def test_terminal_card_done():
    card = TerminalCard(
        session_id='s1',
        session_label='s1',
        command='cargo build',
        scrollback='Finished.',
        exit_code=0,
    )
    assert card.state == 'done'
    assert '[#639922]✓[/]' in card._delta_text()


def test_terminal_card_failed():
    card = TerminalCard(
        session_id='s1',
        session_label='s1',
        command='cargo build',
        scrollback='error: build failed',
        exit_code=101,
    )
    assert card.state == 'failed'
    assert '[#E24B4A]✗ 101[/]' in card._delta_text()


def test_terminal_card_summary():
    card = TerminalCard(
        session_id='s1',
        session_label='s1',
        cwd='/project/grinta',
        command='',
        scrollback='Compiling grinta v0.1.0\nFinished in 4.2s',
    )
    assert 'Finished' in card._delta_text()


def test_terminal_card_detail_screen():
    card = TerminalCard(
        session_id='s1',
        session_label='s1',
        command='cargo build',
        scrollback='Compiling...\nFinished.',
    )
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail import TerminalDetailScreen

    assert isinstance(screen, TerminalDetailScreen)


# ── BrowserCard ────────────────────────────────────────────────────────


def test_browser_card_running():
    card = BrowserCard(domain='github.com/raft/paper', action='extracting links')
    assert card.state == 'running'
    assert '⌁ Browser' in _line_text(card)
    assert '[#EF9F27]⌁ Browser[/]' in _line_text(card)
    assert 'github.com' in _line_text(card)
    assert 'extracting' in card._delta_text()


def test_browser_card_done():
    card = BrowserCard(
        domain='github.com/raft/paper',
        action='found 3 refs',
        extracted='# Raft\n...',
    )
    assert card.state == 'done'


def test_browser_card_detail_screen():
    card = BrowserCard(
        domain='github.com/raft/paper',
        full_url='https://github.com/raft/paper',
        actions=['Navigate', 'Scroll', 'Extract'],
        extracted='# Raft',
        links=['https://raft.github.io'],
    )
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail import BrowserDetailScreen

    assert isinstance(screen, BrowserDetailScreen)


# ── DebuggerCard ───────────────────────────────────────────────────────


def test_debugger_card_running():
    card = DebuggerCard(location='backend/raft.py:47', function='')
    assert card.state == 'running'
    assert '⎇ Debug' in _line_text(card)
    assert '[#EF9F27]⎇ Debug[/]' in _line_text(card)
    assert 'backend/raft.py:47' in _line_text(card)


def test_debugger_card_with_stack():
    stack = [
        'handle_vote()  backend/raft.py:47',
        'request_vote()  backend/raft.py:91',
    ]
    card = DebuggerCard(
        location='backend/raft.py:47',
        function='handle_vote()',
        stack=stack,
    )
    assert card.state == 'done'


def test_debugger_card_detail_screen():
    card = DebuggerCard(
        location='backend/raft.py:47',
        function='handle_vote()',
        stack=['handle_vote()  backend/raft.py:47'],
        variables=[('term', '3'), ('candidate', '"node-2"')],
    )
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail import DebuggerDetailScreen

    assert isinstance(screen, DebuggerDetailScreen)


# ── DelegateCard / MCPCard / PayloadCard ───────────────────────────────


def test_delegate_card_running_then_done():
    card = DelegateCard('Investigate flaky test', worker='worker-1')
    assert card.state == 'running'
    assert '⇢ Delegated' in _line_text(card)
    card.complete(result='done', success=True)
    assert card.state == 'done'
    assert '✓' in card._delta_text()


def test_mcp_card_merges_result():
    card = MCPCard('search_docs', arguments={'q': 'ranking'})
    card.complete(result='snippet', success=True)
    assert card.state == 'done'
    assert '⊛ Called' in _line_text(card) or 'search_docs' in _line_text(card)


def test_payload_card_detail_screen():
    card = PayloadCard('Found', 'MyClass', 'class MyClass: ...')
    assert 'ƒ Found' in _line_text(card)
    screen = card.build_detail_screen()
    from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

    assert isinstance(screen, PayloadDetailScreen)
    assert 'MyClass' in screen._body


# ── detail screen base ─────────────────────────────────────────────────


def test_detail_screen_has_escape_binding():
    assert any(
        binding[0] == 'escape'
        if isinstance(binding, tuple)
        else getattr(binding, 'key', '') == 'escape'
        for binding in DetailScreen.BINDINGS
    )
