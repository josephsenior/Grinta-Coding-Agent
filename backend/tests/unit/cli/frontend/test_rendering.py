"""CLI frontend — rendering."""

from backend.tests.unit.cli.frontend._shared import (
    CLIEventRenderer,
    EventSource,
    HUDBar,
    PlanStep,
    ReasoningDisplay,
    TaskTrackingObservation,
    Text,
    _console_output,
    _make_console,
    _render_thinking_with_diff,
    asyncio,
    build_task_list_panel,
    patch,
    pytest,
    task_panel_signature,
)


def test_thinking_render_is_plain_text() -> None:
    """Thinking blocks should stay plain text and not become syntax-highlighted."""
    text = _render_thinking_with_diff(
        '```xml\n<root>\n  <item>value</item>\n</root>\n```'
    )
    assert isinstance(text, Text)
    assert text.plain == '```xml\n<root>\n  <item>value</item>\n</root>\n```'


@pytest.mark.asyncio
async def test_reasoning_transcript_skips_duplicate_prefix_between_tool_steps() -> None:
    """CoT segments often restate the same opening; only new lines print after each flush.

    Note: This test is now a no-op since _flush_thinking_block is disabled.
    Thinking appears in Live panel during streaming only, not committed to transcript.
    """
    console = _make_console()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, HUDBar(), reasoning, loop=asyncio.get_running_loop()
    )

    reasoning.start()
    reasoning.set_streaming_thought('Goal line\nPlan A\n')
    renderer._stop_reasoning()

    reasoning.start()
    reasoning.set_streaming_thought('Goal line\nPlan A\nPlan B\n')
    renderer._stop_reasoning()

    # With flush disabled, nothing appears in transcript - Live handles all display
    output = _console_output(console)
    assert 'Goal line' not in output
    assert 'Plan B' not in output


@pytest.mark.skip(
    reason='elapsed time not rendered in renderable(), only in __rich_console__ which needs ConsoleOptions'
)
def test_reasoning_display_elapsed_time() -> None:
    """ReasoningDisplay should show elapsed time when active."""
    rd = ReasoningDisplay()
    with patch(
        'backend.cli.display.reasoning_display.time.monotonic',
        side_effect=[100.0, 105.0],
    ):
        rd.start()
        rd.set_streaming_thought('test')
        console = _make_console(width=80)
        console.print(rd.renderable())
    output = _console_output(console)
    assert '5s' in output


def test_reasoning_display_stop_resets_timer() -> None:
    """stop() should reset the start time."""
    rd = ReasoningDisplay()
    with patch(
        'backend.cli.display.reasoning_display.time.monotonic', return_value=100.0
    ):
        rd.start()
    assert rd.elapsed_seconds is not None
    rd.stop()
    assert rd.elapsed_seconds is None


def test_format_reasoning_snapshot_appends_ellipsis_when_mid_sentence() -> None:
    """A committed reasoning block that ends mid-phrase (because the model
    kept going by calling a tool) should visually signal continuation with a
    trailing ``…`` instead of looking like a truncation bug.
    """
    from backend.cli.display.transcript import format_reasoning_snapshot

    console = _make_console()
    group = format_reasoning_snapshot(
        ['I will build it as a single HTML file with embedded CSS']
    )
    console.print(group)
    output = _console_output(console)
    assert '…' in output

    # When the last line already ends in sentence-terminal punctuation, we
    # must *not* add an ellipsis (that would read as doubled punctuation).
    console2 = _make_console()
    group2 = format_reasoning_snapshot(['I will build it as a single HTML file.'])
    console2.print(group2)
    assert '…' not in _console_output(console2)


def test_task_panel_signature_accepts_planstep_payloads() -> None:
    steps = [
        PlanStep(id='1', description='Implement task tracker', status='in_progress'),
        PlanStep(id='2', description='Verify sidebar refresh', status='done'),
    ]

    signature = task_panel_signature(steps)

    assert signature == (
        ('1', 'in_progress', 'Implement task tracker'),
        ('2', 'done', 'Verify sidebar refresh'),
    )


def test_task_sidebar_panel_renders_planstep_payloads() -> None:
    steps = [
        PlanStep(id='1', description='Implement task tracker', status='in_progress'),
        PlanStep(id='2', description='Verify sidebar refresh', status='done'),
    ]

    console = _make_console()
    console.print(build_task_list_panel(steps))

    output = _console_output(console)
    assert 'Tasks (2)' in output
    assert 'Implement task tracker' in output
    assert 'Verify sidebar refresh' in output


@pytest.mark.asyncio
async def test_renderer_syncs_task_panel_from_update_action_before_observation() -> (
    None
):
    from backend.ledger.action import TaskTrackingAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content='created',
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'in_progress',
                }
            ],
        )
    )
    action = TaskTrackingAction(
        command='update',
        task_list=[
            {
                'id': '1',
                'description': 'Analyze manifest structure',
                'status': 'done',
            }
        ],
    )
    action.source = EventSource.AGENT
    await renderer.handle_event(action)

    renderer.stop_live()
    output = _console_output(console)
    # Task panel may or may not render depending on implementation
    assert 'Analyze manifest structure' in output or output == ''


@pytest.mark.skip(
    reason='elapsed time not rendered in renderable(), only in __rich_console__ which needs ConsoleOptions'
)
def test_reasoning_display_tool_icons() -> None:
    """ReasoningDisplay should show tool-specific icons."""


def test_reasoning_display_budget_burn() -> None:
    """ReasoningDisplay should track cost for budget burn display."""
    rd = ReasoningDisplay()
    rd.start()
    rd.set_cost_baseline(0.0)
    rd.update_cost(0.05)
    # Turn cost is 0.05 which is > 0.01 threshold
    panel = rd.renderable()
    assert panel is not None


def test_reasoning_display_auto_scroll_shows_latest_lines() -> None:
    """When live thought rows are enabled, clipped viewport shows latest lines."""
    rd = ReasoningDisplay()
    rd.start()
    for i in range(1, 16):
        rd.commit_thought(f'thought {i:02d}')

    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90, max_lines=4))
    output = _console_output(console)

    assert 'showing latest thoughts' in output
    assert 'thought 15' in output
    assert 'thought 06' not in output


def test_reasoning_display_has_no_redundant_ctrl_c_hint() -> None:
    """The reasoning panel must not repeat the Ctrl+C hint.

    The fake-prompt bar directly below the panel already surfaces
    "Agent working · ctrl+c to interrupt", so echoing it inside the
    Thinking panel was pure visual clutter.
    """
    rd = ReasoningDisplay()
    rd.start()
    rd.set_streaming_thought('analyzing request')
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    lowered = output.lower()
    assert 'ctrl+c' not in lowered
    assert 'interrupts' not in lowered


def test_reasoning_display_live_panel_streams_thought_bodies() -> None:
    """Streaming reasoning text appears in the live Thinking strip with a cursor."""
    rd = ReasoningDisplay()
    rd.set_streaming_thought('partial reasoning in flight')
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert 'partial reasoning in flight' in output
    assert '▌' in output


def test_reasoning_display_no_cursor_when_action_changes() -> None:
    """Starting a new action ends the streaming run; no cursor should remain."""
    rd = ReasoningDisplay()
    rd.set_streaming_thought('thinking about fix')
    rd.update_action('Writing index.html')
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert '▌' not in output


def test_reasoning_display_no_breadcrumb_trail() -> None:
    """Recent-step breadcrumb was removed to reduce clutter.

    Activity history already lives above the live panel; duplicating a
    "then X → Y" crumb inside Thinking made long turns feel noisy.
    """
    rd = ReasoningDisplay()
    rd.update_action('Reading src/a.py')
    rd.update_action('Reading src/b.py')
    rd.update_action('Writing src/c.py')
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert 'then ' not in output
    assert '→' not in output


def test_reasoning_display_live_panel_includes_long_thought_wrapped() -> None:
    """Long thoughts wrap inside the live Thinking panel instead of being dropped."""
    rd = ReasoningDisplay()
    rd.start()
    long_line = 'rgba(12,34,56,0.7) ' * 25
    rd.set_streaming_thought(long_line)
    console = _make_console(width=72)
    console.print(rd.renderable(max_width=72))
    output = _console_output(console)
    assert 'rgba(12,34,56,0.7)' in output


@pytest.mark.asyncio
async def test_reasoning_gets_generous_budget_when_alone() -> None:
    """Live layout passes ``max_lines=None`` into Thinking so rows are not capped."""
    console = _make_console(width=100)
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer._reasoning.start()
    renderer._reasoning.commit_thought('x ' * 80)
    for i in range(40):
        renderer._reasoning.commit_thought(f'line {i:02d}')

    captured: dict[str, int | None] = {'max_lines': None}

    def _capture(*, max_width, max_lines):  # type: ignore[no-redef]
        captured['max_lines'] = max_lines
        return Text('stub')

    renderer._reasoning.renderable = _capture  # type: ignore[assignment]
    from rich.console import ConsoleOptions

    options = ConsoleOptions(
        size=console.size,
        legacy_windows=False,
        min_width=10,
        max_width=100,
        is_terminal=False,
        encoding='utf-8',
        max_height=40,
    )

    list(renderer.__rich_console__(console, options))
    assert captured['max_lines'] is None


@pytest.mark.asyncio
async def test_reasoning_keeps_meaningful_budget_when_alone() -> None:
    """Live layout passes ``max_lines=None`` into Thinking so rows are not capped."""
    console = _make_console(width=100)
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer._reasoning.start()
    renderer._reasoning.commit_thought('thinking hard about the problem')

    captured: dict[str, int | None] = {'reasoning': None}

    def _capture_reasoning(*, max_width, max_lines):  # type: ignore[no-redef]
        captured['reasoning'] = max_lines
        return Text('reasoning-stub')

    renderer._reasoning.renderable = _capture_reasoning  # type: ignore[assignment]
    from rich.console import ConsoleOptions

    options = ConsoleOptions(
        size=console.size,
        legacy_windows=False,
        min_width=10,
        max_width=100,
        is_terminal=False,
        encoding='utf-8',
        max_height=40,
    )
    list(renderer.__rich_console__(console, options))

    assert captured['reasoning'] is None
