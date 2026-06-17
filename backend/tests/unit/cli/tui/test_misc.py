"""Headless TUI — misc."""

from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.tui._shared import _fill_scrollable_transcript, _get_screen


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
            from backend.cli.display.hud import HUDBar
            from backend.cli.display.reasoning_display import ReasoningDisplay
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
async def test_handle_input_releases_lock_during_dispatch(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    dispatch_started = asyncio.Event()
    dispatch_continue = asyncio.Event()

    class FakeController:
        def get_agent_state(self):
            return AgentState.RUNNING

    class FakeRenderer:
        async def drain_events_async(self) -> None:
            return None

        def flush_live_ui(self, *, terminal: bool = False) -> None:
            return None

    async def slow_dispatch(text: str) -> None:
        dispatch_started.set()
        await dispatch_continue.wait()

    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    monkeypatch.setattr(GrintaScreen, 'add_user_message', lambda self, text: None)
    monkeypatch.setattr(GrintaScreen, '_scroll_to_bottom', lambda self: None)
    monkeypatch.setattr(GrintaScreen, '_render_hud_bar', lambda self: None)
    monkeypatch.setattr(GrintaScreen, 'finalize_thinking', lambda self: None)
    monkeypatch.setattr(GrintaScreen, 'add_error', lambda self, text: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._controller = FakeController()
        s._renderer = FakeRenderer()
        s._renderer._event_stream = None
        s._dispatch_to_agent = slow_dispatch  # type: ignore[method-assign]

        task = asyncio.create_task(s._handle_input('hello'))
        await asyncio.wait_for(dispatch_started.wait(), timeout=10)
        assert s._turn_in_flight is True
        assert not s._input_lock.locked()

        dispatch_continue.set()
        await asyncio.wait_for(task, timeout=10)
        assert s._turn_in_flight is False


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


@pytest.mark.asyncio
async def test_bootstrap_setup_renderer_marks_ready_before_hydrate(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    hydrate_started = asyncio.Event()

    async def slow_hydrate(*_args, **_kwargs):
        hydrate_started.set()
        await asyncio.Event().wait()

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        controller = MagicMock()
        controller.get_agent_state.return_value = AgentState.LOADING
        event_stream = MagicMock()
        event_stream.sid = 'test-session'

        renderer = TUIRenderer(
            console=console,
            hud=s._hud,
            reasoning=s._reasoning,
            tui=s,
            loop=loop,
        )
        renderer.hydrate_recent_transcript = slow_hydrate  # type: ignore[method-assign]
        renderer.drain_events_async = AsyncMock(return_value=None)  # type: ignore[method-assign]
        s._renderer = renderer

        await s._bootstrap_setup_renderer(event_stream, controller)

        assert s._hud.state.agent_state_label == 'awaiting_user_input'
        await asyncio.wait_for(hydrate_started.wait(), timeout=2.0)


@pytest.mark.asyncio
async def test_drain_invocation_budget_reschedules_with_backlog(
    mock_config, monkeypatch
):
    from collections import deque
    from threading import Lock

    from backend.cli.tui.renderer import drain as drain_mod

    orch = MagicMock()
    orch._async_drain_active = False
    orch._pending_events = deque()
    orch._pending_lock = Lock()
    orch._drain_scheduled = False
    orch._pending_events_dropped = 0
    orch._history = []
    orch._loop = MagicMock()
    orch._tui = MagicMock()
    orch._render_prep_cache = {}
    orch._process_event = MagicMock()
    orch.flush_live_ui = MagicMock()
    orch.flush_pending_final_commits = AsyncMock(return_value=None)
    orch._refresh_display = MagicMock()

    for idx in range(8):
        event = SimpleNamespace(id=idx)
        orch._pending_events.append(event)

    clock = iter([0.0, 0.0, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02])
    monkeypatch.setattr(drain_mod, '_TUI_DRAIN_FRAME_BUDGET_SECONDS', 0.02)
    monkeypatch.setattr(drain_mod, '_TUI_DRAIN_INVOCATION_BUDGET_SECONDS', 0.03)
    monkeypatch.setattr(drain_mod.time, 'monotonic', lambda: next(clock, 0.05))
    monkeypatch.setattr(
        drain_mod, '_preprocess_event_async', AsyncMock(return_value=None)
    )
    post_drain = MagicMock()
    monkeypatch.setattr(drain_mod, '_force_immediate_drain', post_drain)

    await drain_mod.drain_events_async(orch)

    assert orch._process_event.call_count >= 1
    assert post_drain.called
    assert len(orch._pending_events) > 0


@pytest.mark.asyncio
async def test_drain_respects_frame_budget(mock_config, monkeypatch):
    from backend.cli.tui.renderer import drain as drain_mod
    from backend.cli.tui.renderer import processor as processor_mod

    orch = MagicMock()
    processed: list[int] = []

    def counting_process(_orch, event):
        processed.append(getattr(event, 'id', -1))

    events = [SimpleNamespace(id=idx) for idx in range(6)]
    clock = iter([0.0, 0.0, 0.05, 0.05, 0.05, 0.05, 0.05])

    monkeypatch.setattr(drain_mod, '_TUI_DRAIN_FRAME_BUDGET_SECONDS', 0.02)
    monkeypatch.setattr(drain_mod.time, 'monotonic', lambda: next(clock, 0.05))
    monkeypatch.setattr(
        drain_mod, '_preprocess_event_async', AsyncMock(return_value=None)
    )
    monkeypatch.setattr(processor_mod, '_process_event', counting_process)
    orch._process_event = lambda event: counting_process(orch, event)

    count = await drain_mod._process_events_with_frame_budget(orch, events)
    assert count < len(events)
    assert count >= 1


@pytest.mark.asyncio
async def test_viewport_keeps_bounded_child_count(mock_config):
    from backend.cli.tui.constants import _TUI_VIEWPORT_MAX_MOUNTED

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        display = s._get_display()
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        for idx in range(_TUI_VIEWPORT_MAX_MOUNTED + 15):
            widget = Static(f'row-{idx}')
            setattr(widget, '_ledger_event_id', idx)
            display.mount(widget)
        await pilot.pause()
        display.sync_viewport(renderer)
        await pilot.pause()
        assert display.child_widget_count <= _TUI_VIEWPORT_MAX_MOUNTED


def test_no_pending_event_drop_under_burst(monkeypatch):
    from backend.cli.tui.renderer import drain as drain_mod
    from backend.ledger.observation.terminal import TerminalObservation

    orch = MagicMock()
    orch._pending_events = __import__('collections').deque()
    orch._pending_lock = __import__('threading').Lock()
    orch._drain_scheduled = False
    orch._pending_events_dropped = 0
    orch._min_rendered_event_id = -1
    orch._max_rendered_event_id = -1
    orch._loop = MagicMock()
    orch._loop.call_soon_threadsafe = lambda fn, *args: fn(*args)

    from backend.cli.tui.renderer.mixins import event_processor as ep_mod

    monkeypatch.setattr(ep_mod, '_TUI_PENDING_EVENT_LIMIT', 3)

    for idx in range(5):
        obs = TerminalObservation(
            session_id='s1',
            content=f'chunk-{idx}',
        )
        obs.id = idx
        drain_mod._on_event(orch, obs)

    assert orch._pending_events_dropped == 0
    assert len(orch._pending_events) <= 5


@pytest.mark.asyncio
async def test_tui_scroll_badge_shows_and_follows_tail(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        display = _get_screen(app).query_one('#main-display')
        await _fill_scrollable_transcript(display, pilot)
        display.user_scroll_page_up(animate=False)
        await pilot.pause()

        badge = display.query_one('#scroll-badge', ScrollTailBadge)
        assert display._user_scrolled_away is True
        assert not badge.has_class('-hidden')

        display.append_widget(Static('new activity'))
        await pilot.pause()
        assert display._tail_unread_count == 1

        badge.post_message(ScrollTailBadge.FollowRequested())
        await pilot.pause()
        assert display._user_scrolled_away is False
        assert badge.has_class('-hidden')


def test_unified_diff_view_does_not_create_nested_scroll() -> None:
    """Diff bodies should scroll with the transcript, not trap the wheel."""
    from textual.containers import VerticalScroll

    from backend.cli.tui.widgets.unified_diff_view import UnifiedDiffView

    assert not issubclass(UnifiedDiffView, VerticalScroll)
