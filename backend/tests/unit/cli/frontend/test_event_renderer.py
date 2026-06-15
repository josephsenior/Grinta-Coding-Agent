"""CLI frontend — event_renderer."""

from backend.tests.unit.cli.frontend import _shared
from backend.tests.unit.cli.frontend._shared import *  # noqa: F403
for _name in dir(_shared):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_shared, _name)

@pytest.mark.asyncio
async def test_event_renderer_updates_metrics_and_streaming_preview() -> None:
    """Metrics update still works, streaming preview removed."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    metrics = Metrics()
    metrics.accumulated_cost = 1.25
    metrics.token_usages = [
        TokenUsage(prompt_tokens=10, completion_tokens=5, context_window=1000)
    ]

    chunk = StreamingChunkAction(chunk='Hello', accumulated='Hello', is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert hud.state.cost_usd == 1.25
    assert hud.state.context_tokens == 10
    assert hud.state.context_limit == 1000

    final_message = MessageAction(content='Hello', wait_for_response=True)
    final_message.source = EventSource.AGENT
    await renderer.handle_event(final_message)

    # Agent reply printed to console (no Live active).
    output = _console_output(console)
    assert 'Hello' in output

@pytest.mark.asyncio
async def test_event_renderer_emits_each_duplicate_command_line() -> None:
    """Each CmdRunAction produces a Ran row; command is shown when observation or next action arrives."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()
    run1 = CmdRunAction(command='ls -F')
    run1.source = EventSource.AGENT
    run2 = CmdRunAction(command='ls -F')
    run2.source = EventSource.AGENT
    renderer._process_event_data(run1)
    renderer._process_event_data(run2)
    # run1 is flushed when run2 arrives (orphan flush); run2 is still buffered
    assert _transcript_needle_count(console, '$ ls -F') == 1

    renderer._process_event_data(CmdOutputObservation('', command='ls -F'))
    run3 = CmdRunAction(command='ls -F')
    run3.source = EventSource.AGENT
    renderer._process_event_data(run3)
    # CmdOutputObservation printed run2’s combined card; run3 is buffered (flushed when run4 or obs arrives)
    assert _transcript_needle_count(console, '$ ls -F') == 2

@pytest.mark.asyncio
async def test_event_renderer_repeats_identical_file_read_rows() -> None:
    """Same read path after another tool still gets a new activity row each time."""
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()
    r1 = FileReadAction(path='pkg/a.py')
    r1.source = EventSource.AGENT
    other = FileEditAction(path='pkg/b.py', command='replace_string')
    other.source = EventSource.AGENT
    r2 = FileReadAction(path='pkg/a.py')
    r2.source = EventSource.AGENT
    renderer._process_event_data(r1)
    renderer._process_event_data(FileReadObservation(content='a\nb', path='pkg/a.py'))
    renderer._process_event_data(other)
    renderer._process_event_data(r2)
    renderer._process_event_data(FileReadObservation(content='a\nb', path='pkg/a.py'))
    assert _transcript_needle_count(console, 'pkg/a.py') == 2
    assert _transcript_needle_count(console, 'Read') == 2

@pytest.mark.asyncio
async def test_event_renderer_message_action_between_reads_both_emit_rows() -> None:
    """Assistant MessageAction between two identical reads does not suppress either row."""
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()
    r1 = FileReadAction(path='x.py')
    r1.source = EventSource.AGENT
    msg = MessageAction(content='Thinking out loud…', wait_for_response=False)
    msg.source = EventSource.AGENT
    r2 = FileReadAction(path='x.py')
    r2.source = EventSource.AGENT
    renderer._process_event_data(r1)
    renderer._process_event_data(FileReadObservation(content='alpha', path='x.py'))
    renderer._process_event_data(msg)
    renderer._process_event_data(r2)
    renderer._process_event_data(FileReadObservation(content='beta', path='x.py'))
    assert _transcript_needle_count(console, 'x.py') == 2

@pytest.mark.asyncio
async def test_event_renderer_repeat_command_after_error_still_two_rows() -> None:
    """Errors flush buffered command; second run shows up after its own observation."""
    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()
    run1 = CmdRunAction(command='ls -la')
    run1.source = EventSource.AGENT
    renderer._process_event_data(run1)
    renderer._process_event_data(ErrorObservation(content='oops'))
    run2 = CmdRunAction(command='ls -la')
    run2.source = EventSource.AGENT
    renderer._process_event_data(run2)
    # run1 was flushed (orphan) by ErrorObservation; run2 is printed by its matching observation
    renderer._process_event_data(
        CmdOutputObservation('output', exit_code=0, command='ls -la')
    )
    assert _transcript_needle_count(console, '$ ls -la') == 2
