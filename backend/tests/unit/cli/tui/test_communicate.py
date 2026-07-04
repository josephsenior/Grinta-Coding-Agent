"""Headless TUI — communicate."""

from backend.tests.unit.cli.tui._shared import (
    ClarificationRequestAction,
    CommunicatePromptWidget,
    ConfirmRequestAction,
    EscalateToHumanAction,
    GrintaScreen,
    GrintaTUIApp,
    InformAction,
    ProposalAction,
    RichConsole,
    TextArea,
    UncertaintyAction,
    WelcomeWidget,
    _get_screen,
    asyncio,
    pytest,
)


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

        await pilot.click(
            items[0],
            offset=(1, 0),
        )
        await pilot.pause()

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

        s.query_one(CommunicatePromptWidget)
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
