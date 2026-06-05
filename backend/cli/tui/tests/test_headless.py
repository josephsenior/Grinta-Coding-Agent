"""Headless TUI smoke tests — run without a terminal."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole
from rich.markdown import Markdown
from textual.containers import Container
from textual.widgets import Label, Select, Static, TextArea

from backend.cli._event_renderer.unified_renderer import ActivityRenderer
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import grinta_rich_theme_styles
from backend.cli.tui.app import (
    HUD,
    CommunicatePromptWidget,
    GrintaHelpDialog,
    GrintaScreen,
    GrintaSessionsDialog,
    InputBar,
    RendererDrainRequested,
    TUIRenderer,
    WelcomeWidget,
    _strip_terminal_control_literals,
)
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.activity_card import (
    ActivityCard as TUIActivityCard,
)
from backend.cli.tui.widgets.activity_card import (
    AgentMessage,
    DiffLine,
    PlanMessage,
    SplitDiffLine,
    ThinkingIndicator,
    TurnCompletion,
)
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import (
    AgentThinkAction,
    ClarificationRequestAction,
    CondensationRequestAction,
    ConfirmRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    InformAction,
    MessageAction,
    ProposalAction,
    StreamingChunkAction,
    UncertaintyAction,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentThinkObservation,
    StatusObservation,
)
from backend.ledger.observation.agent import (
    AgentStateChangedObservation,
    DelegateTaskObservation,
)
from backend.ledger.observation.browser_screenshot import BrowserScreenshotObservation
from backend.ledger.observation.code_nav import LspQueryObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import (
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
)
from backend.ledger.observation.mcp import MCPObservation
from backend.ledger.observation.task_tracking import TaskTrackingObservation
from backend.ledger.observation.terminal import TerminalObservation


@pytest.fixture
def mock_config():
    config = MagicMock()
    type(config).project_root = PropertyMock(return_value=None)

    llm_config = MagicMock()
    llm_config.model = 'openai/gpt-4o'
    llm_config.base_url = None
    config.get_llm_config.return_value = llm_config
    config.get_llm_config_from_agent.return_value = llm_config
    return config


def _get_screen(app: GrintaTUIApp) -> GrintaScreen:
    """Helper: query via app.screen since app.query_one uses default screen."""
    return app.screen  # type: ignore[return-value]


def test_grinta_rich_theme_overrides_inline_markdown_code(monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('GRINTA_NO_COLOR', raising=False)

    style = grinta_rich_theme_styles()['markdown.code']

    assert 'cyan' not in style.lower()
    assert 'magenta' not in style.lower()
    assert '#101829' in style


async def _fill_scrollable_transcript(display, pilot, *, count: int = 80) -> None:
    for idx in range(count):
        display.append_widget(Static(f'transcript line {idx}'))
    await pilot.pause()
    display.force_scroll_end()
    await pilot.pause()
    assert display.max_scroll_y > 0


def test_tui_plan_message_renders_structured_plan_card():
    action = SimpleNamespace(
        final_thought='Plan produced.',
        outputs={
            'status': 'completed',
            'summary': 'Plan produced.',
            'plan': ['Inspect `backend/cli/hud.py`.', 'Run tests.'],
            'files_or_areas': ['backend/cli/hud.py'],
            'risks': ['Estimated provider usage.'],
            'verification': [
                '`uv run pytest backend/tests/unit/cli/test_cli_frontend.py -q`'
            ],
            'assumptions': ['Metrics are present.'],
            'next_step': 'Switch to Agent Mode.',
        },
    )

    widget = PlanMessage(action)

    console = RichConsole(record=True, width=100)
    console.print(widget.renderable)
    rendered = console.export_text()
    assert 'Plan Ready' in rendered
    assert 'Execution Plan' in rendered
    assert 'backend/cli/hud.py' in rendered


def test_tui_plan_message_renders_adaptive_finish_sections():
    action = SimpleNamespace(
        final_thought='Here is the recommended plan.',
        outputs={
            'mode': 'plan',
            'status': 'completed',
            'response': 'Here is the recommended plan.',
            'summary': 'Produced an adaptive plan.',
            'sections': [
                {
                    'title': 'Objective',
                    'items': ['Improve finish output across task types.'],
                },
                {
                    'title': 'Recommended Plan',
                    'items': ['Update schema.', 'Normalize handlers.', 'Verify rendering.'],
                },
                {
                    'title': 'Verification Strategy',
                    'items': ['Run finish and TUI renderer tests.'],
                },
            ],
            'evidence': {
                'status': 'planned',
                'details': 'Based on the finish schema and renderer paths.',
            },
            'open_items': ['Decide whether to add a generic Agent finish card.'],
            'next_step': 'Switch to Agent Mode.',
        },
    )

    widget = PlanMessage(action)

    console = RichConsole(record=True, width=100)
    console.print(widget.renderable)
    rendered = console.export_text()
    assert 'Plan Ready' in rendered
    assert 'Objective' in rendered
    assert 'Recommended Plan' in rendered
    assert 'Evidence / Verification' in rendered
    assert 'Open Items' in rendered


@pytest.mark.asyncio
async def test_tui_mounts(mock_config):
    """Smoke test — TUI mounts without CSS or runtime errors."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        stats = s.query_one('#hud-line-1', Label)
        assert stats is not None
        assert 'GRINTA' in str(stats.renderable)

        footer = s.query_one('#hud-bar', HUD)
        assert footer is not None


@pytest.mark.asyncio
async def test_tui_input_and_transcript(mock_config):
    """Verify the input area and transcript log are present."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        assert ta is not None

        input_bar = s.query_one('#input-bar', InputBar)
        assert 'processing' not in input_bar.classes


@pytest.mark.asyncio
async def test_tui_activity_card_processing_and_mount(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.shell_command('git status')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='running',
            outcome=data.secondary,
            extra_content=None,
            collapsed=True,
        )
        mounted.set_processing(True)
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        assert found is not None


@pytest.mark.asyncio
async def test_tui_activity_card_expanded_output_wraps_in_extra_frame(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.terminal_output('line1\nline2', session_id='term-1')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='ok',
            outcome=data.secondary,
            extra_content='line1\nline2',
            collapsed=False,
        )
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        body = found.query_one('#expanded-body', Container)
        assert body is not None
        assert body.display is True


@pytest.mark.asyncio
async def test_tui_activity_card_body_click_collapses(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.terminal_output('line1\nline2', session_id='term-1')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='ok',
            outcome=data.secondary,
            extra_content='line1\nline2',
            collapsed=False,
        )
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        extra = found.query_one('#extra', Static)

        event = SimpleNamespace(
            widget=extra,
            prevented=False,
            stopped=False,
            prevent_default=lambda: setattr(event, 'prevented', True),
            stop=lambda: setattr(event, 'stopped', True),
        )
        found.on_click(event)

        body = found.query_one('#expanded-body', Container)
        assert found._collapsed is True
        assert body.display is False
        assert event.prevented is True
        assert event.stopped is True


@pytest.mark.asyncio
async def test_tui_renderer_writes_expandable_cards_collapsed_by_default(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        card = ActivityRenderer.shell_command(
            'python fail.py',
            output='Traceback\nboom',
            exit_code=1,
        )
        assert card.is_collapsible is True
        assert card.start_collapsed is False

        widget = renderer._write_card(card)
        await pilot.pause()

        body = widget.query_one('#expanded-body', Container)
        assert widget._collapsed is True
        assert body.display is False


@pytest.mark.asyncio
async def test_tui_live_response_follows_tail_when_not_user_scrolled(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        await _fill_scrollable_transcript(display, pilot)

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer.update_live_response('Starting response.')
        await pilot.pause()
        display.force_scroll_end()
        await pilot.pause()

        renderer.update_live_response(
            'Starting response.\n' + '\n'.join(f'new line {idx}' for idx in range(20))
        )
        await pilot.pause()

        assert display._user_scrolled_away is False
        assert display._was_at_bottom()


@pytest.mark.asyncio
async def test_tui_live_response_respects_user_scrolled_away(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        await _fill_scrollable_transcript(display, pilot)

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer
        renderer.update_live_response('Starting response.')
        await pilot.pause()
        display.force_scroll_end()
        await pilot.pause()

        display.user_scroll_page_up(animate=False)
        await pilot.pause()
        assert display._user_scrolled_away is True

        renderer.update_live_response(
            'Starting response.\n' + '\n'.join(f'new line {idx}' for idx in range(20))
        )
        await pilot.pause()

        assert display._user_scrolled_away is True
        assert not display._was_at_bottom()


@pytest.mark.asyncio
async def test_tui_typing(mock_config):
    """Verify typing text into the input area works."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        assert ta.focusable

        await pilot.press(*'hello world')
        assert ta.text == 'hello world'


@pytest.mark.asyncio
async def test_tui_welcome_arrow_navigation_works_with_input_focus(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(1.1)

        welcome = s.query_one(WelcomeWidget)
        assert welcome.select_current() == 'Explain this codebase'

        await pilot.press('down')
        await pilot.pause()
        assert (
            welcome.select_current()
            == 'Analyze this repository and produce an implementation plan'
        )

        await pilot.press('up')
        await pilot.pause()
        assert welcome.select_current() == 'Explain this codebase'


@pytest.mark.asyncio
async def test_tui_welcome_click_submits_selected_suggestion(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        submit_mock = MagicMock()
        s.action_submit_input = submit_mock  # type: ignore[method-assign]
        s._show_welcome()
        await pilot.pause(1.1)

        welcome = s.query_one(WelcomeWidget)
        items = list(welcome.query('.welcome-item'))
        assert len(items) == 5

        clicked = await pilot.click(items[1], offset=(1, 0))
        await pilot.pause()

        ta = s.query_one('#input', TextArea)
        assert clicked
        assert ta.text == 'Analyze this repository and produce an implementation plan'
        assert s._welcome_visible is False
        submit_mock.assert_called_once()


@pytest.mark.asyncio
async def test_tui_communicate_clarification_supports_keyboard_selection(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        captured: list[str] = []

        async def _fake_handle_input(text: str) -> None:
            captured.append(text)

        s._handle_input = _fake_handle_input  # type: ignore[method-assign]
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]
        s.add_communicate_clarification(
            ClarificationRequestAction(
                question='Which direction should I take?',
                options=['Keep the API as-is', 'Refactor the public API'],
                context='A scope choice is required before continuing.',
            )
        )
        await pilot.pause()

        card = s.query_one(CommunicatePromptWidget)
        ta = s.query_one('#input', TextArea)
        ta.focus()

        assert card.current_value == 'Keep the API as-is'

        await pilot.press('down')
        await pilot.pause()
        assert card.current_value == 'Refactor the public API'

        await pilot.press('enter')
        await pilot.pause()

        # The chosen value is wrapped in a scaffold that includes the
        # question, so the LLM can see what was being asked.
        assert len(captured) == 1
        assert 'Refactor the public API' in captured[0]
        assert 'Which direction should I take?' in captured[0]


@pytest.mark.asyncio
async def test_tui_communicate_proposal_click_submits_selected_option(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        captured: list[str] = []

        async def _fake_handle_input(text: str) -> None:
            captured.append(text)

        s._handle_input = _fake_handle_input  # type: ignore[method-assign]
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]
        s.add_communicate_proposal(
            ProposalAction(
                rationale='There are two reasonable ways to continue.',
                recommended=1,
                options=[
                    {
                        'name': 'Patch the current flow',
                        'description': 'Keep the current surface and fix the bug in place.',
                    },
                    {
                        'name': 'Rework the flow',
                        'description': 'Clean the interaction up before adding more behavior.',
                    },
                ],
            )
        )
        await pilot.pause()

        card = s.query_one(CommunicatePromptWidget)
        items = list(card.query('.welcome-item'))
        assert 'recommended' in str(items[1].renderable).lower()
        assert 'Keep the current surface and fix the bug in place.' in str(
            items[0].renderable
        )

        clicked = await pilot.click(
            items[0],
            offset=(1, 0),
        )
        await pilot.pause()

        assert clicked
        assert len(captured) == 1
        assert 'Patch the current flow' in captured[0]


@pytest.mark.asyncio
async def test_tui_communicate_proposal_marks_recommended_in_label(
    mock_config, monkeypatch
):
    """Proposal with `recommended=1` labels the second option as recommended.

    We deliberately do NOT pre-highlight the recommended option: the
    ``(recommended)`` suffix is the cue, and the user navigates to it.
    Pre-selection would race the widget's mount order.
    """
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]
        s.add_communicate_proposal(
            ProposalAction(
                rationale='Two options.',
                recommended=1,
                options=[
                    {'name': 'Option A', 'description': 'first'},
                    {'name': 'Option B', 'description': 'second'},
                    {'name': 'Option C', 'description': 'third'},
                ],
            )
        )
        await pilot.pause()
        await pilot.pause()

        card = s.query_one(CommunicatePromptWidget)
        # The recommended option carries a visual suffix; the other two
        # do not. No pre-selection: the user navigates with arrow keys.
        assert 'Option B (recommended)' in card._suggestions
        assert 'Option A (recommended)' not in card._suggestions
        assert 'Option C (recommended)' not in card._suggestions
        # The default selection is the first option, as before.
        assert card.current_value == 'Option A'


@pytest.mark.asyncio
async def test_tui_communicate_uncertainty_renders_informational_card(
    mock_config, monkeypatch
):
    """Uncertainty action renders a card with the concerns but doesn't block input."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]

        s.add_communicate_uncertainty(
            UncertaintyAction(
                uncertainty_level=0.2,
                specific_concerns=['maybe wrong file', 'maybe wrong regex'],
                requested_information='the exact file path',
                thought='I am not sure which file to look at.',
            )
        )
        await pilot.pause()

        # The card exists in the transcript.
        cards = list(display.query(CommunicatePromptWidget))
        assert len(cards) == 1
        card = cards[0]
        # Header carries the title; subheader carries the concerns.
        assert 'Needs Context' in card._header_text
        assert 'maybe wrong file' in card._subheader_text
        assert 'the exact file path' in card._subheader_text

        # Uncertainty is non-blocking: the active communicate card is None.
        assert s._active_communicate_card is None


@pytest.mark.asyncio
async def test_tui_communicate_escalate_renders_structured_attempts(
    mock_config, monkeypatch
):
    """Escalation card renders structured attempts as readable lines."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]

        s.add_communicate_escalate(
            EscalateToHumanAction(
                reason='All ripgrep variants returned empty.',
                attempts_made=[
                    {'action': 'rg --files', 'result': 'no match'},
                    {'action': 'rg pattern', 'result': 'permission denied'},
                ],
                specific_help_needed='Confirm the file path or paste the file content.',
            )
        )
        await pilot.pause()

        cards = list(display.query(CommunicatePromptWidget))
        assert len(cards) == 1
        card = cards[0]
        # Header carries the title; subheader carries the attempts and help.
        assert 'Need Your Input' in card._header_text
        assert 'rg --files' in card._subheader_text
        assert 'permission denied' in card._subheader_text
        assert 'Help needed' in card._subheader_text


@pytest.mark.asyncio
async def test_tui_communicate_confirm_renders_with_safe_default_selected(
    mock_config, monkeypatch
):
    """Confirm card always blocks; default_index=1 (deny) is pre-selected."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        captured: list[str] = []

        async def _fake_handle_input(text: str) -> None:
            captured.append(text)

        s._handle_input = _fake_handle_input  # type: ignore[method-assign]
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]

        s.add_communicate_confirm(
            ConfirmRequestAction(
                question='Delete the user table?',
                options=['Yes, do it', 'No, abort'],
                default_index=1,
            )
        )
        await pilot.pause()
        await pilot.pause()

        card = s.query_one(CommunicatePromptWidget)
        # The deny option (index 1) is pre-selected for safety.
        assert card.current_value == 'No, abort'

        # Confirm always blocks; the active card is set.
        assert s._active_communicate_card is card

        await pilot.press('enter')
        await pilot.pause()

        # Entering on "No, abort" submits it as the user reply.
        assert len(captured) == 1
        assert 'No, abort' in captured[0]


@pytest.mark.asyncio
async def test_tui_communicate_inform_renders_without_blocking(
    mock_config, monkeypatch
):
    """Inform action writes a card but never blocks the input."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]

        s.add_communicate_inform(
            InformAction(
                text='I created helper.py and tests for the parser.',
                context='Two new files added.',
            )
        )
        await pilot.pause()

        cards = list(display.query(CommunicatePromptWidget))
        assert len(cards) == 1
        card = cards[0]
        # Header carries the title; subheader/context carry the body text.
        assert 'Status' in card._header_text
        assert 'helper.py' in card._header_text or 'helper.py' in card._subheader_text

        # Inform never blocks; the active card is None.
        assert s._active_communicate_card is None


@pytest.mark.asyncio
async def test_tui_communicate_selection_scaffolds_user_reply_with_question(
    mock_config, monkeypatch
):
    """When the user picks a communicate option, the LLM sees the question context."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        captured: list[str] = []

        async def _fake_handle_input(text: str) -> None:
            captured.append(text)

        s._handle_input = _fake_handle_input  # type: ignore[method-assign]
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]
        s.add_communicate_clarification(
            ClarificationRequestAction(
                question='Which direction should I take?',
                options=['Keep the API as-is', 'Refactor the public API'],
            )
        )
        await pilot.pause()

        card = s.query_one(CommunicatePromptWidget)
        await pilot.press('down')
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()

        # The captured text should now include the question scaffolding,
        # so the LLM knows what was being asked even if the conversation
        # has scrolled out of view.
        assert len(captured) == 1
        reply = captured[0]
        assert 'Refactor the public API' in reply
        assert 'Which direction should I take?' in reply
        assert 'user answered the prompt' in reply


@pytest.mark.asyncio
async def test_tui_communicate_clarification_supports_structured_options(
    mock_config, monkeypatch
):
    """Clarification options with {label, description} dicts are rendered."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]

        s.add_communicate_clarification(
            ClarificationRequestAction(
                question='Which library?',
                options=[
                    {'label': 'requests', 'description': 'simple, sync'},
                    {'label': 'httpx', 'description': 'async support'},
                ],
            )
        )
        await pilot.pause()

        cards = list(display.query(CommunicatePromptWidget))
        assert len(cards) == 1
        card = cards[0]
        # The card has the values, and submitting one works.
        assert card.has_options is True
        assert 'requests' in card._values
        assert 'httpx' in card._values


@pytest.mark.asyncio
async def test_tui_communicate_prompt_blocks_welcome_empty_state(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        s._hide_welcome()
        s._write_log = display.append_widget  # type: ignore[method-assign]
        s.add_communicate_clarification(
            ClarificationRequestAction(
                question='Which direction should I take?',
                options=['Keep the API as-is', 'Refactor the public API'],
            )
        )
        await pilot.pause()

        assert s._transcript_has_real_content() is True

        s._show_welcome()
        await pilot.pause()

        assert len(list(display.query(CommunicatePromptWidget))) == 1
        assert (
            len([child for child in display.children if type(child) is WelcomeWidget])
            == 0
        )


@pytest.mark.asyncio
async def test_tui_hud_bar_shows_workspace_path(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._render_hud_bar()
        await pilot.pause()

        stats = s.query_one('#hud-line-1', Label)
        rendered = str(stats.renderable)
        assert 'Ws:' in rendered
        assert any(sep in rendered for sep in ('/', '\\', '~'))


@pytest.mark.asyncio
async def test_tui_welcome_persists_until_real_transcript_content(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(0.2)
        assert s._welcome_visible is True

        s.on_renderer_drain_requested(RendererDrainRequested())
        await pilot.pause()
        assert s._welcome_visible is True

        s._get_display().mount(Static('boot complete'))
        await pilot.pause()
        s.on_renderer_drain_requested(RendererDrainRequested())
        await pilot.pause()
        assert s._welcome_visible is False


def test_tui_strips_leaked_mouse_reports_from_input_text() -> None:
    leaked = '[<35;73;29M[<35;73;30Mhello\x1b[<35;74;31M'
    assert _strip_terminal_control_literals(leaked) == 'hello'


def test_tui_strips_leaked_mouse_reports_without_sgr_marker() -> None:
    leaked = 'PS> [444444;32;15M[555;31;16Mhello'
    assert _strip_terminal_control_literals(leaked) == 'PS> hello'


@pytest.mark.asyncio
async def test_tui_input_removes_leaked_mouse_reports_live(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '[<35;73;29Mhello[<35;73;30M'
        await pilot.pause()

        assert ta.text == 'hello'


@pytest.mark.asyncio
async def test_tui_clear_command(mock_config):
    """Verify /clear slash command works."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/clear'
        await pilot.press('enter')
        await pilot.pause()

        assert s is not None


@pytest.mark.asyncio
async def test_tui_help_shows(mock_config):
    """Verify /help opens the dedicated help modal."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        opened: dict[str, object | None] = {'dialog': None}

        def _fake_push_screen(dialog) -> None:
            opened['dialog'] = dialog

        app.push_screen = _fake_push_screen  # type: ignore[method-assign]
        ta = s.query_one('#input', TextArea)
        ta.text = '/help'
        await pilot.press('enter')
        await pilot.pause()

        assert isinstance(opened['dialog'], GrintaHelpDialog)


@pytest.mark.asyncio
async def test_tui_settings_command_dispatches(mock_config):
    """Verify /settings dispatches to the real TUI settings handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        called = {'value': False}

        async def _fake_settings() -> None:
            called['value'] = True

        s._open_settings_tui = _fake_settings  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/settings'
        await pilot.press('enter')
        await pilot.pause()

        assert called['value'] is True


@pytest.mark.asyncio
async def test_tui_sessions_command_dispatches_with_args(mock_config):
    """Verify /sessions forwards parsed args to the session handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_sessions(args: list[str]) -> None:
            captured.extend(args)

        s._run_sessions_tui = _fake_sessions  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --limit 7'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['--limit', '7']


@pytest.mark.asyncio
async def test_tui_resume_command_dispatches_with_args(mock_config):
    """Verify /resume forwards parsed args to the resume handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_resume(args: list[str]) -> None:
            captured.extend(args)

        s._run_resume_tui = _fake_resume  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/resume 3'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['3']


@pytest.mark.asyncio
async def test_tui_sessions_modal_resume_handoff(mock_config):
    """Verify sessions modal selection triggers direct resume flow."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        resumed: dict[str, str | None] = {'sid': None}

        async def _fake_push_screen_wait(_dialog) -> str | None:
            return 'session-abc123'

        async def _fake_resume_target(target: str) -> None:
            resumed['sid'] = target

        app.push_screen_wait = _fake_push_screen_wait  # type: ignore[method-assign]
        s._resume_session_target = _fake_resume_target  # type: ignore[method-assign]

        await s._run_sessions_tui([])

        assert resumed['sid'] == 'session-abc123'


@pytest.mark.asyncio
async def test_tui_sessions_preview_shows_extended_metadata(
    mock_config, monkeypatch, tmp_path
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    fake_entries = [
        (
            'session-abc123456789',
            {
                'title': 'Fix TUI layout',
                'llm_model': 'openai/gpt-4o',
                'selected_repository': 'Grinta',
                'selected_branch': 'main',
                'trigger': 'gui',
                'accumulated_cost': 1.25,
                'prompt_tokens': 100,
                'completion_tokens': 40,
                'total_tokens': 140,
                'last_updated_at': '2026-05-21T12:00:00',
                'created_at': '2026-05-21T11:30:00',
            },
            42,
        )
    ]

    from backend.cli import session_manager

    monkeypatch.setattr(
        session_manager, '_find_sessions_root', lambda _config=None: tmp_path
    )
    monkeypatch.setattr(
        session_manager,
        '_list_session_entries',
        lambda root, sort_by='updated': fake_entries,
    )
    monkeypatch.setattr(
        session_manager, '_filter_sessions_fuzzy', lambda sessions, search: sessions
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        dialog = GrintaSessionsDialog(mock_config)
        app.push_screen(dialog)
        await pilot.pause()

        preview = dialog.query_one('#sessions-preview')
        rendered = str(preview.renderable)
        assert 'Repository' in rendered
        assert 'Branch' in rendered
        assert 'Tokens' in rendered


@pytest.mark.asyncio
async def test_tui_inline_command_hint_updates(mock_config):
    """Verify slash command typing updates the compact HUD activity line."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --s'
        await pilot.pause()

        hint = s.query_one('#hud-line-2', Label)
        assert 'Help' in str(hint.renderable)


@pytest.mark.asyncio
async def test_tui_command_autocomplete_for_sessions(mock_config):
    """Verify autocomplete expands slash command prefixes."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sess'
        s.action_complete_command()
        await pilot.pause()

        assert ta.text == '/sessions '


@pytest.mark.asyncio
async def test_tui_unknown_command(mock_config):
    """Verify unknown slash command shows error without crashing."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/nonexistent'
        await pilot.press('enter')
        await pilot.pause()

        transcript = s.query_one('#main-display')
        assert transcript is not None


@pytest.mark.asyncio
async def test_tui_update_hud_state(mock_config):
    """Verify update_hud folds runtime info into the two-line HUD."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._hud.update_agent_state('Running')
        s.update_hud()
        await pilot.pause()

        stats = s.query_one('#hud-line-1', Label)
        activity = s.query_one('#hud-line-2', Label)
        assert 'Running' in str(stats.renderable)
        assert 'Help' in str(activity.renderable)


@pytest.mark.asyncio
async def test_tui_hud_bar_shows_accumulated_and_context_tokens(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._hud.state.total_tokens = 430
        s._hud.state.context_tokens = 430
        s._hud.state.context_limit = 8192
        s._render_hud_bar()
        await pilot.pause()

        stats = s.query_one('#hud-line-2', Label)
        rendered = str(stats.renderable)
        assert 'Ctx: 430/8,192' in rendered
        assert '%' in rendered


@pytest.mark.asyncio
async def test_tui_hud_autonomy_selector_updates_controller(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        controller = SimpleNamespace(
            autonomy_controller=SimpleNamespace(autonomy_level='balanced')
        )
        s._controller = controller  # type: ignore[assignment]
        autonomy = s.query_one('#hud-autonomy', Select)
        autonomy.value = 'full'
        await pilot.pause()

        assert controller.autonomy_controller.autonomy_level == 'full'
        assert s._hud.state.autonomy_level == 'full'


@pytest.mark.asyncio
async def test_tui_mode_switch_supports_chat_plan_agent(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        mode_select = s.query_one('#hud-mode', Select)
        for mode in ('chat', 'plan', 'agent'):
            mode_select.value = mode
            await pilot.pause()
            assert agent_config.mode == mode


@pytest.mark.asyncio
async def test_tui_mode_switch_updates_default_agent_config(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    mock_config.default_agent = 'Orchestrator'
    configs = {
        'Orchestrator': SimpleNamespace(mode='agent'),
        'agent': SimpleNamespace(mode='agent'),
    }
    mock_config.get_agent_config.side_effect = lambda name='agent': configs[name]
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._apply_mode('chat')
        await pilot.pause()

        assert configs['Orchestrator'].mode == 'chat'
        assert configs['agent'].mode == 'agent'


@pytest.mark.asyncio
async def test_tui_mode_switch_updates_running_agent_config(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        running_config = SimpleNamespace(mode='agent')
        planner = SimpleNamespace(
            _config=running_config,
            build_toolset=MagicMock(return_value=['read']),
        )
        agent = SimpleNamespace(
            config=running_config,
            planner=planner,
            tools=['old'],
        )
        s._controller = SimpleNamespace(
            agent=agent,
            state=SimpleNamespace(extra_data={'active_run_mode': 'agent'}),
        )

        s._apply_mode('chat')
        await pilot.pause()

        assert agent_config.mode == 'chat'
        assert running_config.mode == 'chat'
        assert agent.tools == ['read']
        assert 'active_run_mode' not in s._controller.state.extra_data


@pytest.mark.asyncio
async def test_tui_autonomy_visibility_follows_mode(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        autonomy = s.query_one('#hud-autonomy', Select)
        autonomy_label = s.query_one('#hud-label-autonomy', Label)

        s._apply_mode('chat')
        await pilot.pause()
        assert autonomy.display is False
        assert autonomy_label.display is False

        s._apply_mode('plan')
        await pilot.pause()
        assert autonomy.display is False
        assert autonomy_label.display is False

        s._apply_mode('agent')
        await pilot.pause()
        assert autonomy.display is True
        assert autonomy_label.display is True


@pytest.mark.asyncio
async def test_tui_composer_placeholder_changes_by_mode(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        hint = s.query_one('#input-hint', Label)

        s._apply_mode('chat')
        await pilot.pause()
        assert 'Ask about the codebase or architecture...' in str(hint.renderable)

        s._apply_mode('plan')
        await pilot.pause()
        assert 'Describe what Grinta should inspect and plan...' in str(hint.renderable)

        s._apply_mode('agent')
        await pilot.pause()
        assert 'Describe a task for Grinta to execute...' in str(hint.renderable)


@pytest.mark.asyncio
async def test_tui_sidebar_rows_expose_delete_for_mcp_and_skills(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    mock_config.mcp = SimpleNamespace(
        servers=[SimpleNamespace(name='server-a', type='stdio')]
    )

    from backend.cli._event_renderer import sidebar as sidebar_module

    monkeypatch.setattr(sidebar_module, '_load_playbook_skills', lambda: ['skill-a'])

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._refresh_display()

        rows = s.query(SidebarRow).results()
        deletable = [row for row in rows if getattr(row, 'deletable', False)]
        assert any(getattr(row, 'item_id', '') == 'mcp:server-a' for row in deletable)
        assert any(getattr(row, 'item_id', '') == 'skill:skill-a' for row in deletable)


@pytest.mark.asyncio
async def test_tui_task_sidebar_does_not_clear_on_empty_view_payload(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (1)'


@pytest.mark.asyncio
async def test_tui_task_sidebar_does_not_clear_on_ambiguous_empty_update_payload(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        renderer._process_event(
            TaskTrackingObservation(
                content='task tracker sync complete',
                command='update',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (1)'


@pytest.mark.asyncio
async def test_tui_task_sidebar_allows_explicit_empty_update_clear(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        renderer._process_event(
            TaskTrackingObservation(
                content='✅ Plan updated with 0 tasks. Now begin implementing the first todo task.',
                command='update',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (0)'

        renderer._process_event(
            TaskTrackingObservation(
                content='viewed',
                command='view',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (0)'


@pytest.mark.asyncio
async def test_tui_terminal_session_reuses_single_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(TerminalRunAction(command='npm run dev'))
        renderer._process_event(TerminalReadAction(session_id='term-1'))
        renderer._process_event(
            TerminalObservation(session_id='term-1', content='ready')
        )
        renderer._process_event(
            TerminalInputAction(session_id='term-1', input='status')
        )
        await pilot.pause()

        cards = s.query(TUIActivityCard).results()
        terminal_cards = [card for card in cards if 'category-terminal' in card.classes]
        assert len(terminal_cards) == 1

        collapsed = terminal_cards[0].query_one('#collapsed-row')
        assert '$ status' in str(collapsed.renderable) or 'Sent' in str(
            collapsed.renderable
        )


@pytest.mark.asyncio
async def test_tui_terminal_observation_strips_control_traffic(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(TerminalRunAction(command='powershell'))
        renderer._process_event(
            TerminalObservation(
                session_id='term-1',
                content='PS> \x1b[32mok\x1b[0m [444444;32;15Mdone',
            )
        )
        await pilot.pause()

        card = next(
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-terminal' in card.classes
        )
        extra = card.query_one('#extra')
        rendered = (
            str(extra.renderable.plain)
            if hasattr(extra.renderable, 'plain')
            else str(extra.renderable)
        )
        assert '\x1b' not in rendered
        assert '[444444;32;15M' not in rendered


@pytest.mark.asyncio
async def test_tui_shell_command_reuses_single_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(CmdRunAction(command='pytest -q'))
        renderer._process_event(
            CmdOutputObservation('2 passed', command='pytest -q', exit_code=0)
        )
        await pilot.pause()

        cards = s.query(TUIActivityCard).results()
        shell_cards = [card for card in cards if 'category-shell' in card.classes]
        assert len(shell_cards) == 1
        collapsed = shell_cards[0].query_one('#collapsed-row')
        assert '$ pytest -q' in str(collapsed.renderable) or 'Shell' in str(
            collapsed.renderable
        )
        assert 'exit 0' in str(collapsed.renderable)


@pytest.mark.asyncio
async def test_tui_lsp_query_merges_action_and_observation_into_single_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            LspQueryAction(
                file='app.py',
                command='find_definition',
                line=1,
                column=1,
                symbol='MyClass',
            )
        )
        renderer._process_event(
            LspQueryObservation(
                content='app.py:10:1 - class MyClass',
                available=True,
            )
        )
        await pilot.pause()

        code_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-code' in card.classes
        ]
        assert len(code_cards) == 1
        assert 'processing' not in code_cards[0].classes
        collapsed = code_cards[0].query_one('#collapsed-row')
        rendered = str(collapsed.renderable)
        assert 'Analyzed' in rendered
        assert 'MyClass' in rendered
        assert 'completed' in rendered


@pytest.mark.asyncio
async def test_tui_mcp_call_merges_action_and_observation_into_single_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            MCPAction(name='search_docs', arguments={'q': 'ranking'})
        )
        renderer._process_event(
            MCPObservation(
                name='search_docs',
                arguments={'q': 'ranking'},
                content='Result snippet for ranking.',
            )
        )
        await pilot.pause()

        mcp_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-mcp' in card.classes
        ]
        assert len(mcp_cards) == 1
        assert 'processing' not in mcp_cards[0].classes
        collapsed = mcp_cards[0].query_one('#collapsed-row')
        rendered = str(collapsed.renderable)
        assert 'Called' in rendered
        assert 'search_docs' in rendered
        assert 'completed' in rendered


@pytest.mark.asyncio
async def test_tui_delegate_task_merges_action_and_observation_into_single_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            DelegateTaskAction(
                task_description='Investigate flaky test',
            )
        )
        renderer._process_event(
            DelegateTaskObservation(
                content='Worker finished successfully.',
                success=True,
            )
        )
        await pilot.pause()

        worker_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-workers' in card.classes
        ]
        assert len(worker_cards) == 1
        assert 'processing' not in worker_cards[0].classes
        collapsed = worker_cards[0].query_one('#collapsed-row')
        rendered = str(collapsed.renderable)
        assert 'Delegated' in rendered
        assert 'completed' in rendered


@pytest.mark.asyncio
async def test_tui_browser_screenshot_merges_with_action_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            BrowserToolAction(
                command='navigate',
                params={'url': 'https://example.com'},
            )
        )
        renderer._process_event(
            BrowserScreenshotObservation(
                image_path='/tmp/snap.png',
                content='page captured',
            )
        )
        await pilot.pause()

        browser_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-browser' in card.classes
        ]
        assert len(browser_cards) == 1
        assert 'processing' not in browser_cards[0].classes
        collapsed = browser_cards[0].query_one('#collapsed-row')
        rendered = str(collapsed.renderable)
        assert 'Navigate' in rendered
        assert 'done' in rendered


@pytest.mark.asyncio
async def test_tui_agent_message_action_renders_response(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        action = MessageAction(content='I can help with that.')
        action.source = EventSource.AGENT
        renderer._process_event(action)

        assert renderer._last_final_response_text == 'I can help with that.'
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)
        assert isinstance(renderer._history[0].renderable, Markdown)


@pytest.mark.asyncio
async def test_tui_final_stream_and_message_action_do_not_duplicate(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Final answer.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        final_message = MessageAction(content='Final answer.')
        final_message.source = EventSource.AGENT
        renderer._process_event(final_message)

        assert renderer._last_final_response_text == 'Final answer.'
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)
        assert isinstance(renderer._history[0].renderable, Markdown)


@pytest.mark.asyncio
async def test_tui_final_stream_commits_response(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Plain preview.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        assert renderer._last_final_response_text == 'Plain preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)

        suppressed = MessageAction(content='', suppress_cli=True)
        suppressed.source = EventSource.AGENT
        renderer._process_event(suppressed)

        assert renderer._last_final_response_text == 'Plain preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2


@pytest.mark.asyncio
async def test_tui_final_stream_empty_accumulated_commits_live_response(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        # Stream chunk with content (not final)
        chunk = StreamingChunkAction(
            accumulated='Live content preview.',
            is_final=False,
        )
        chunk.source = EventSource.AGENT
        renderer._process_event(chunk)

        assert renderer._live_response == 'Live content preview.'
        assert len(renderer._history) == 0

        # Final stream chunk with empty content
        final_stream = StreamingChunkAction(
            accumulated='',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        # Should fall back to live response and commit it
        assert renderer._last_final_response_text == 'Live content preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)


@pytest.mark.asyncio
async def test_tui_final_stream_suppresses_live_response_for_tool_call(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        chunk = StreamingChunkAction(
            accumulated='I will inspect the workspace.',
            is_final=False,
        )
        chunk.source = EventSource.AGENT
        renderer._process_event(chunk)

        assert renderer._live_response == 'I will inspect the workspace.'
        assert len(renderer._history) == 0

        final_stream = StreamingChunkAction(
            accumulated='',
            is_final=True,
            suppress_live_response=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        assert renderer._last_final_response_text == ''
        assert renderer._live_response == ''
        assert len(renderer._history) == 0


@pytest.mark.asyncio
async def test_tui_streamed_response_clears_before_tool_action(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        stream = StreamingChunkAction(
            accumulated='I will inspect the workspace.',
            is_final=False,
        )
        stream.source = EventSource.AGENT
        renderer._process_event(stream)

        command = CmdRunAction(command='Get-Location')
        command.source = EventSource.AGENT
        renderer._process_event(command)

        assert renderer._last_final_response_text == ''
        assert renderer._live_response == ''
        assert len(renderer._history) == 0


@pytest.mark.asyncio
async def test_tui_duplicate_thinking_payload_renders_once(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        thought = 'Inspecting the render path.'
        renderer._process_event(StreamingChunkAction(thinking_accumulated=thought))
        renderer._process_event(AgentThinkAction(thought=thought))
        renderer._process_event(AgentThinkObservation(content=thought))
        renderer._process_event(
            FileWriteAction(path='demo.txt', content='finalize thinking')
        )
        await pilot.pause()

        thinking_blocks = list(s.query(ThinkingIndicator).results())
        assert len(thinking_blocks) == 1
        rendered = str(thinking_blocks[0].query_one('#thinking-body', Static).renderable)
        assert rendered.count(thought) == 1


@pytest.mark.asyncio
async def test_tui_thinking_indicator_collapses_into_expandable_card(mock_config):
    """After thinking ends, the block collapses to ``Thought for Ns ▸`` with
    a hidden body. Clicking (or pressing enter) toggles expansion."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        thought = 'Plotting the next move.'
        renderer._process_event(StreamingChunkAction(thinking_accumulated=thought))
        renderer._process_event(
            FileWriteAction(path='demo.txt', content='finalize thinking')
        )
        await asyncio.sleep(0.2)

        # Exactly one ThinkingIndicator, and it has collapsed.
        blocks = list(s.query(ThinkingIndicator).results())
        assert len(blocks) == 1
        block = blocks[0]
        assert block._finalized is True
        assert block._collapsed is True

        body = block.query_one('#thinking-body', Static)
        assert '-hidden' in body.classes
        # The thought is still in the body — just hidden.
        assert thought in str(body.renderable)

        # Toggle via the public action (same as the enter/space binding).
        block.action_toggle()
        assert block._collapsed is False
        assert '-hidden' not in body.classes

        # Toggle back to collapsed.
        block.action_toggle()
        assert block._collapsed is True
        assert '-hidden' in body.classes


@pytest.mark.asyncio
async def test_tui_search_results_in_thinking_payload_render_as_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            AgentThinkAction(
                thought='[SEARCH_RESULTS]\nbackend/app.py:12:render thinking'
            )
        )
        await pilot.pause()

        assert list(s.query(ThinkingIndicator).results()) == []
        search_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-search' in card.classes
        ]
        assert len(search_cards) == 1
        collapsed = search_cards[0].query_one('#collapsed-row')
        assert 'Search' in str(collapsed.renderable)


@pytest.mark.asyncio
async def test_tui_internal_thinking_payloads_render_as_activity_cards(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            AgentThinkAction(thought="[WORKING_MEMORY] Updated 'findings' section.")
        )
        renderer._process_event(
            AgentThinkAction(
                thought='[CHECKPOINT] Saved checkpoint before edit.',
                source_tool='checkpoint',
            )
        )
        await pilot.pause()

        assert list(s.query(ThinkingIndicator).results()) == []
        cards = list(s.query(TUIActivityCard).results())
        memory_cards = [card for card in cards if 'category-memory' in card.classes]
        tool_cards = [card for card in cards if 'category-tool' in card.classes]

        assert len(memory_cards) == 1
        assert len(tool_cards) == 1
        assert 'Memory' in str(memory_cards[0].query_one('#collapsed-row').renderable)
        assert 'Checkpoint' in str(tool_cards[0].query_one('#collapsed-row').renderable)


@pytest.mark.asyncio
async def test_tui_recoverable_error_renders_as_plain_error_message(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            AgentThinkAction(
                thought="Invalid task status 'doing'. Use one of: blocked, in_progress, done, skipped, todo.",
                kind=AgentThinkAction.KIND_RECOVERABLE_ERROR,
            )
        )
        # The mock config causes the background bootstrap to fail with an
        # AgentNotRegisteredError, which keeps `pilot.pause()` from settling
        # (a pending message sits in the screen's call_later queue). Yield
        # briefly to let the Static error widget mount, then assert directly
        # against the renderer's history.
        await asyncio.sleep(0.3)

        assert list(s.query(ThinkingIndicator).results()) == []
        # Recoverable errors now render as a plain bold red message — same path
        # as the "no tools detected" ErrorObservation — not as an ActivityCard.
        cards = list(s.query(TUIActivityCard).results())
        error_cards = [card for card in cards if 'category-error' in card.classes]
        assert error_cards == []

        # The error must be in the renderer's history (the source of truth).
        history_text = '\n'.join(
            str(r) for r in renderer._history if r is not None
        )
        assert "Invalid task status 'doing'" in history_text


@pytest.mark.asyncio
async def test_tui_compaction_status_renders_persistent_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        hud = HUDBar()
        renderer = TUIRenderer(
            console=console,
            hud=hud,
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        status = StatusObservation(
            content='Compacting context...',
            status_type='compaction',
        )
        status.source = EventSource.AGENT
        renderer._process_event(status)
        await pilot.pause()

        cards = s.query(TUIActivityCard).results()
        compaction_cards = [
            card for card in cards if 'category-tool' in card.classes
        ]
        assert len(compaction_cards) == 1
        collapsed = compaction_cards[0].query_one('#collapsed-row')
        assert 'Compacting (1st)' in str(collapsed.renderable)
        assert 'context' in str(collapsed.renderable)
        assert renderer._compaction_transcript_active is True
        assert renderer._condensation_count == 1


@pytest.mark.asyncio
async def test_tui_condensation_request_reuses_status_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        renderer._process_event(CondensationRequestAction())
        renderer._process_event(
            AgentCondensationObservation('Compacted summary for the next turn.')
        )
        await pilot.pause()

        compaction_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-tool' in card.classes
        ]
        assert len(compaction_cards) == 2

        started = compaction_cards[0].query_one('#collapsed-row')
        completed = compaction_cards[1].query_one('#collapsed-row')
        assert 'Compacting (1st)' in str(started.renderable)
        assert 'Compacted (1st)' in str(completed.renderable)
        assert 'Done' in str(completed.renderable)
        assert renderer._compaction_transcript_active is False


@pytest.mark.asyncio
async def test_tui_final_stream_and_normalized_message_do_not_duplicate(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Final answer.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        final_message = MessageAction(
            content='<function_calls></function_calls>\nFinal answer.'
        )
        final_message.source = EventSource.AGENT
        renderer._process_event(final_message)

        assert renderer._last_final_response_text == 'Final answer.'
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)


@pytest.mark.asyncio
async def test_tui_file_write_renders_compact_create_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(FileWriteAction(path='demo.txt', content='alpha\nbeta'))
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        card = file_cards[0]
        collapsed = card.query_one('#collapsed-row')
        assert 'demo.txt' in str(collapsed.renderable)
        assert '+2' in str(collapsed.renderable)
        assert card._collapsible is False
        assert card.query_one('#expanded-body').display is False


@pytest.mark.asyncio
async def test_tui_file_write_does_not_dump_created_file_body(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileWriteAction(
                path='demo.txt',
                content='# This is a test file\nIt contains multiple sections',
            )
        )
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        collapsed = file_cards[0].query_one('#collapsed-row')
        assert 'demo.txt' in str(collapsed.renderable)


@pytest.mark.asyncio
async def test_tui_file_edit_create_action_renders_non_expandable_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        create_action = FileEditAction(
            path='created.txt',
            command='create_file',
            file_text='alpha\nbeta',
        )
        renderer._process_event(create_action)
        renderer._process_event(create_action)
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        card = file_cards[0]
        collapsed = card.query_one('#collapsed-row')
        assert 'Created' in str(collapsed.renderable)
        assert 'created.txt' in str(collapsed.renderable)
        assert '+2' in str(collapsed.renderable)
        assert card._collapsible is False
        assert not list(card.query('#caret').results())
        assert card.query_one('#expanded-body').display is False

        renderer._process_event(
            FileEditObservation(
                path='created.txt',
                content='created',
                prev_exist=False,
                new_content='alpha\nbeta',
            )
        )
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1


@pytest.mark.asyncio
async def test_tui_file_read_card_completes_without_expanded_body(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        long_path = 'backend/cli/tui/some/really/long/path/that/should/not/stretch/read_card.py'
        renderer._process_event(FileReadAction(path=long_path))
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        assert file_cards[0]._collapsible is False
        assert file_cards[0].query_one('#expanded-body').display is False

        renderer._process_event(
            FileReadObservation(path=long_path, content='alpha\nbeta\ngamma')
        )
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        card = file_cards[0]
        collapsed_markup = card._build_collapsed_markup()
        assert 'Read' in collapsed_markup
        assert 'lines' not in collapsed_markup.lower()
        assert '#f6ff8f' not in collapsed_markup
        assert '[blink' not in collapsed_markup
        assert len(card._detail) <= 80
        assert card._collapsible is False
        assert not list(card.query('#caret').results())
        assert card.query_one('#expanded-body').display is False

        renderer._process_event(
            FileReadAction(path='backend/cli/tui/ranged_read.py', view_range=[50, 100])
        )
        renderer._process_event(
            FileReadObservation(
                path='backend/cli/tui/ranged_read.py',
                content='selected\nrange',
            )
        )
        await pilot.pause()

        ranged_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes and 'ranged_read.py' in card._detail
        ]
        assert len(ranged_cards) == 1
        ranged_markup = ranged_cards[0]._build_collapsed_markup()
        assert '50:100' in ranged_markup
        assert '#f6ff8f' in ranged_markup
        assert 'lines' not in ranged_markup.lower()


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_unified_diff_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='demo.txt',
                prev_exist=True,
                old_content='alpha\nbeta\n',
                new_content='alpha\ngamma\nbeta\n',
            )
        )
        await pilot.pause()

        split_rows = list(s.query(SplitDiffLine).results())
        assert split_rows
        assert any(
            row.left_text == ''
            and row.right_text.startswith('+')
            and 'gamma' in row.right_text
            for row in split_rows
        )
        assert any(
            row.left_kind == 'ctx' and row.right_kind == 'ctx' for row in split_rows
        )


@pytest.mark.asyncio
async def test_tui_file_edit_action_and_observation_render_single_delta_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditAction(path='demo.txt', command='edit', new_str='gamma\n')
        )
        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='demo.txt',
                prev_exist=True,
                old_content='alpha\nbeta\n',
                new_content='alpha\ngamma\n',
            )
        )
        await pilot.pause()

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        assert len(file_cards) == 1
        collapsed_markup = file_cards[0]._build_collapsed_markup()
        assert 'demo.txt' in collapsed_markup
        assert '[#54efae]+1[/]' in collapsed_markup
        assert '[#fd8383]-1[/]' in collapsed_markup


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_explicit_diff_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='.',
                prev_exist=True,
                diff='--- demo.txt\n+++ demo.txt\n@@ -1 +1 @@\n-old\n+new\n',
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(DiffLine).results())
        diff_text = [row.renderable.plain for row in diff_rows]
        assert any(line.startswith('--- demo.txt') for line in diff_text)
        assert any(line.startswith('+new') for line in diff_text)

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        collapsed_markup = file_cards[0]._build_collapsed_markup()
        assert '[#54efae]+1[/]' in collapsed_markup
        assert '[#fd8383]-1[/]' in collapsed_markup


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_diff_preview_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content=(
                    'edited\n\n<DIFF_PREVIEW>\n'
                    '--- demo.txt\n+++ demo.txt\n@@ -1 +1 @@\n-old\n+new\n'
                    '</DIFF_PREVIEW>'
                ),
                path='demo.txt',
                prev_exist=True,
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(DiffLine).results())
        diff_text = [row.renderable.plain for row in diff_rows]
        assert any(line.startswith('--- demo.txt') for line in diff_text)
        assert any(line.startswith('+new') for line in diff_text)

        file_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-files' in card.classes
        ]
        collapsed_markup = file_cards[0]._build_collapsed_markup()
        assert '[#54efae]+1[/]' in collapsed_markup
        assert '[#fd8383]-1[/]' in collapsed_markup


@pytest.mark.asyncio
async def test_tui_file_write_observation_uses_diff_preview_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileWriteObservation(
                content=(
                    'wrote\n\n<DIFF_PREVIEW>\n'
                    '--- config.toml\n+++ config.toml\n@@ -1 +1 @@\n-old\n+new\n'
                    '</DIFF_PREVIEW>'
                ),
                path='config.toml',
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(DiffLine).results())
        diff_text = [row.renderable.plain for row in diff_rows]
        assert any(line.startswith('--- config.toml') for line in diff_text)
        assert any(line.startswith('+new') for line in diff_text)


@pytest.mark.asyncio
async def test_tui_renderer_receives_queued_agent_message_events(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.ledger import EventStream
        from backend.persistence.in_memory_file_store import InMemoryFileStore
        from backend.utils.async_utils import set_main_event_loop

        set_main_event_loop(loop)
        stream = EventStream('tui-render-test', InMemoryFileStore(), user_id='tui-test')
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer
        renderer.subscribe(stream, stream.sid)

        try:
            stream.add_event(
                MessageAction(content='Queued agent reply.'),
                EventSource.AGENT,
            )
            await renderer.wait_for_activity(wait_timeout_sec=2.0)
        finally:
            stream.close()

        assert renderer._last_final_response_text == 'Queued agent reply.'
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)
        assert isinstance(renderer._history[0].renderable, Markdown)


@pytest.mark.asyncio
async def test_tui_shell_command_empty_output_still_completes(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(CmdRunAction(command='true'))
        renderer._process_event(CmdOutputObservation('', command='true', exit_code=0))
        await pilot.pause()

        cards = s.query(TUIActivityCard).results()
        shell_cards = [card for card in cards if 'category-shell' in card.classes]
        assert len(shell_cards) == 1
        assert 'processing' not in shell_cards[0].classes


@pytest.mark.asyncio
async def test_tui_turn_completion_uses_full_width_thin_widget(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(CmdRunAction(command='true'))
        renderer._process_event(
            AgentStateChangedObservation(content='', agent_state='awaiting_user_input')
        )

        completion = next(
            item for item in renderer._history if isinstance(item, TurnCompletion)
        )
        assert completion is not None
        rendered = str(completion.renderable)
        assert 'Finished in:' in rendered
        assert 'tool' not in rendered.lower()


def test_activity_renderer_keeps_error_heavy_success_output_expanded() -> None:
    card = ActivityRenderer.shell_command(
        'pytest',
        output='Validation failed on line 12',
        exit_code=0,
    )
    assert card.is_collapsible is True
    assert card.start_collapsed is False


def test_activity_renderer_keeps_failed_delegation_open() -> None:
    card = ActivityRenderer.delegation(
        'Fix parser',
        result='Validation failed in worker',
        success=False,
    )
    assert card.secondary == 'failed'
    assert card.secondary_kind == 'err'
    assert card.start_collapsed is False


@pytest.mark.asyncio
async def test_tui_message_helpers(mock_config):
    """Verify message writing helpers work without error."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.add_user_message('test user message')
        s.add_agent_message('test agent message')
        s.add_system_message('test system message')
        s.add_success('test success')
        s.add_error('test error')
        s.add_warning('test warning')
        s.add_tool_start('test_tool_name')
        s.add_tool_result('test tool result')
        s.add_divider()
        await pilot.pause()

        log = s.query_one('#main-display')
        assert log is not None


@pytest.mark.asyncio
async def test_tui_recoverable_error_routes_to_add_warning(mock_config):
    """Recoverable ErrorObservations must render via add_warning, not add_error."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        s.add_warning = MagicMock(wraps=s.add_warning)  # type: ignore[method-assign]
        s.add_error = MagicMock(wraps=s.add_error)  # type: ignore[method-assign]

        # Recoverable tool-validation outcome → warning path.
        renderer._process_event(
            ErrorObservation(content='Tool validation failed: bad args')
        )
        # User-facing auth failure → still red error path.
        renderer._process_event(
            ErrorObservation(
                content='401 Unauthorized',
                notify_ui_only=True,
            )
        )
        await asyncio.sleep(0.1)

        assert s.add_warning.call_count == 1
        assert s.add_error.call_count == 1
        warning_text = s.add_warning.call_args[0][0]
        error_text = s.add_error.call_args[0][0]
        assert 'Tool validation failed' in warning_text
        assert '401 Unauthorized' in error_text


@pytest.mark.asyncio
async def test_tui_add_error_and_warning_omit_hardcoded_wrap(mock_config):
    """add_error/add_warning must not pre-wrap text — let the container wrap."""
    from backend.cli.tui._app_screen_messages_mixin import (
        _AppScreenMessagesMixin,
    )

    long_text = 'recoverable ' + ('x' * 200)
    # Use a stub class to exercise the helper without spinning up Textual.
    stub = _AppScreenMessagesMixin.__new__(_AppScreenMessagesMixin)
    captured: list[object] = []
    stub._write_log = lambda renderable: captured.append(renderable)  # type: ignore[attr-defined]

    stub.add_error('boom')
    stub.add_warning(long_text)
    plain = '\n'.join(
        str(getattr(item, 'plain', item)) for item in captured
    )
    # The 200-char run must remain on a single line — no width=80 pre-wrap.
    assert 'x' * 200 in plain


@pytest.mark.asyncio
async def test_tui_run_agent_loop_is_awaitable(mock_config):
    """Verify _run_agent_loop is a proper coroutine (architectural check)."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        assert asyncio.iscoroutinefunction(s._run_agent_loop)


@pytest.mark.asyncio
async def test_tui_dispatch_enqueues_user_message_before_starting_agent(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    class FakeController:
        def get_agent_state(self):
            return AgentState.AWAITING_USER_INPUT

    class FakeEventStream:
        def __init__(self) -> None:
            self.events: list[tuple] = []

        def add_event(self, event, source) -> None:
            self.events.append((event, source))

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        event_stream = FakeEventStream()
        ensure_seen_counts: list[int] = []

        async def fake_ensure_agent_task() -> None:
            ensure_seen_counts.append(len(event_stream.events))

        s._controller = FakeController()
        s._event_stream = event_stream
        s._renderer = None
        s._ensure_agent_task = fake_ensure_agent_task  # type: ignore[method-assign]

        await s._dispatch_to_agent('hello')

        assert ensure_seen_counts == [1]
        assert event_stream.events[0][1] == EventSource.USER
        assert event_stream.events[0][0].content == 'hello'


@pytest.mark.asyncio
async def test_tui_handle_input_does_not_bootstrap_twice_after_background_ready(
    mock_config,
    monkeypatch,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    calls = 0

    class FakeController:
        def get_agent_state(self):
            return AgentState.AWAITING_USER_INPUT

    async def fake_bootstrap(self, session_id=None):
        nonlocal calls
        calls += 1
        marker = asyncio.Event()
        self._bootstrapping = marker
        self._controller = FakeController()
        marker.set()

    monkeypatch.setattr(GrintaScreen, '_bootstrap', fake_bootstrap)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._dispatch_to_agent = AsyncMock()  # type: ignore[method-assign]

        await s._handle_input('hello')

        assert calls == 1
        s._dispatch_to_agent.assert_awaited_once_with('hello')


@pytest.mark.asyncio
async def test_tui_drain_events_noop_when_empty(mock_config, monkeypatch):
    """Verify drain_events is safe to call with no pending events."""
    console = RichConsole()
    loop = asyncio.get_running_loop()

    # Prevent _bootstrap from failing and exiting the app
    from backend.cli.tui.app import GrintaScreen

    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())

    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = s._renderer
        if renderer is not None:
            renderer.drain_events()
        else:
            from backend.cli.hud import HUDBar
            from backend.cli.reasoning_display import ReasoningDisplay
            from backend.cli.tui.app import TUIRenderer

            renderer = TUIRenderer(
                console=console,
                hud=HUDBar(),
                reasoning=ReasoningDisplay(),
                tui=s,
                loop=loop,
            )
            renderer.drain_events()


@pytest.mark.asyncio
async def test_tui_stats_panel_exists(mock_config):
    """Verify stats panel in input bar is present."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        stats = s.query_one('#hud-bar')
        assert stats is not None
