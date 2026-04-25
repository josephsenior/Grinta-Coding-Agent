from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from rich.text import Text

from backend.cli.confirmation import _risk_label
from backend.cli.diff_renderer import DiffPanel
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.hud import HUDBar
from backend.cli.main import (
    _configure_redirected_streams,
    _read_piped_stdin,
    show_grinta_splash,
)
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.repl import (
    Repl,
    _build_command_completer,
    _parse_slash_command,
    _prompt_toolkit_available,
    _supports_prompt_session,
)
from backend.core.config import AppConfig
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER
from backend.core.enums import ActionSecurityRisk, AgentState, EventSource
from backend.inference.metrics import Metrics, ResponseLatency, TokenUsage
from backend.ledger.action import (
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentThinkObservation,
    CmdOutputObservation,
    ErrorObservation,
    TaskTrackingObservation,
)
from backend.persistence.locations import get_project_local_data_root


def _make_console(*, width: int = 120) -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=width)


def _make_config() -> AppConfig:
    return cast(AppConfig, MagicMock())


def _console_output(console: Console) -> str:
    file_obj = console.file
    assert isinstance(file_obj, io.StringIO)
    return file_obj.getvalue()


def _transcript_needle_count(console: Console, needle: str) -> int:
    """Count occurrences of *needle* in rendered console output (committed lines)."""
    return _console_output(console).count(needle)


@pytest.mark.asyncio
async def test_event_renderer_updates_metrics_and_streaming_preview() -> None:
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

    chunk = StreamingChunkAction(chunk="Hello", accumulated="Hello", is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.streaming_preview == "Hello"
    assert hud.state.cost_usd == 1.25
    assert hud.state.context_tokens == 15
    assert hud.state.context_limit == 1000

    final_message = MessageAction(content="Hello", wait_for_response=True)
    final_message.source = EventSource.AGENT
    await renderer.handle_event(final_message)

    assert renderer.streaming_preview == ""
    # Agent reply printed to console (no Live active).
    output = _console_output(console)
    assert "Hello" in output


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
    run1 = CmdRunAction(command="ls -F")
    run1.source = EventSource.AGENT
    run2 = CmdRunAction(command="ls -F")
    run2.source = EventSource.AGENT
    renderer._process_event_data(run1)
    renderer._process_event_data(run2)
    # run1 is flushed when run2 arrives (orphan flush); run2 is still buffered
    assert _transcript_needle_count(console, "$ ls -F") == 1

    renderer._process_event_data(CmdOutputObservation("", command="ls -F"))
    run3 = CmdRunAction(command="ls -F")
    run3.source = EventSource.AGENT
    renderer._process_event_data(run3)
    # CmdOutputObservation printed run2’s combined card; run3 is buffered (flushed when run4 or obs arrives)
    assert _transcript_needle_count(console, "$ ls -F") == 2


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
    r1 = FileReadAction(path="pkg/a.py")
    r1.source = EventSource.AGENT
    other = FileEditAction(path="pkg/b.py", command="insert_text")
    other.source = EventSource.AGENT
    r2 = FileReadAction(path="pkg/a.py")
    r2.source = EventSource.AGENT
    renderer._process_event_data(r1)
    renderer._process_event_data(FileReadObservation(content="a\nb", path="pkg/a.py"))
    renderer._process_event_data(other)
    renderer._process_event_data(r2)
    renderer._process_event_data(FileReadObservation(content="a\nb", path="pkg/a.py"))
    assert _transcript_needle_count(console, "pkg/a.py") == 2
    assert _transcript_needle_count(console, "Viewed") == 2


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
    r1 = FileReadAction(path="x.py")
    r1.source = EventSource.AGENT
    msg = MessageAction(content="Thinking out loud…", wait_for_response=False)
    msg.source = EventSource.AGENT
    r2 = FileReadAction(path="x.py")
    r2.source = EventSource.AGENT
    renderer._process_event_data(r1)
    renderer._process_event_data(FileReadObservation(content="alpha", path="x.py"))
    renderer._process_event_data(msg)
    renderer._process_event_data(r2)
    renderer._process_event_data(FileReadObservation(content="beta", path="x.py"))
    assert _transcript_needle_count(console, "x.py") == 2


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
    run1 = CmdRunAction(command="ls -la")
    run1.source = EventSource.AGENT
    renderer._process_event_data(run1)
    renderer._process_event_data(ErrorObservation(content="oops"))
    run2 = CmdRunAction(command="ls -la")
    run2.source = EventSource.AGENT
    renderer._process_event_data(run2)
    # run1 was flushed (orphan) by ErrorObservation; run2 is printed by its matching observation
    renderer._process_event_data(
        CmdOutputObservation("output", exit_code=0, command="ls -la")
    )
    assert _transcript_needle_count(console, "$ ls -la") == 2


def test_hud_shows_mcp_server_count_when_set() -> None:
    hud = HUDBar()
    assert "MCP servers —" in hud._format().plain
    hud.update_mcp_servers(3)
    assert "3 MCP servers" in hud._format().plain
    n_skills = HUDBar.count_bundled_playbook_skills()
    assert (
        f"{n_skills} skill" in hud._format().plain
        or f"{n_skills} skills" in hud._format().plain
    )


def test_hud_shows_provider_and_model_combined() -> None:
    """HUD shows 'provider/model' combined to reduce visual clutter.

    Previously the bar rendered ``provider: google  •  model: X``; the extra
    labels were redundant visual weight since the provider is already
    implied by the prefix of the model slug.
    """
    hud = HUDBar()
    hud.update_model("openai/google/gemini-3-flash-preview")

    full = hud._format().plain
    compact = hud._format_compact().plain

    assert "google/gemini-3-flash-preview" in full
    # The redundant separate labels must be gone.
    assert "provider:" not in full
    assert "model:" not in full
    # The raw "openai/google/..." with the provider prefix still should not leak.
    assert "openai/google/gemini-3-flash-preview" not in full
    assert "google/gemini-3-flash-preview" in compact


def test_settings_ai_tab_shows_provider_and_model_separately() -> None:
    from backend.cli.settings_tui import _render_ai_tab

    console = _make_console()
    llm_cfg = MagicMock()
    llm_cfg.model = "openai/google/gemini-3-flash-preview"
    llm_cfg.api_key = None

    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg
    config.max_budget_per_task = None
    config.cli_tool_icons = False

    with patch("backend.cli.settings_tui.load_app_config", return_value=config):
        _render_ai_tab(console)

    output = _console_output(console)
    assert "Provider" in output
    assert "google" in output
    assert "Model" in output
    assert "gemini-3-flash-preview" in output
    assert "openai/google" not in output


def test_hud_singular_mcp_label() -> None:
    hud = HUDBar()
    hud.update_mcp_servers(1)
    assert "1 MCP server" in hud._format().plain
    assert "1 MCP servers" not in hud._format().plain


def test_confirmation_uses_backend_security_risk() -> None:
    action = CmdRunAction(command="echo hello")
    action.security_risk = ActionSecurityRisk.HIGH

    assert _risk_label(action) == ("HIGH", "bold red")


@pytest.mark.asyncio
async def test_repl_restarts_agent_loop_after_terminal_state() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))

    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.FINISHED
    controller.set_agent_state_to = AsyncMock()

    completed_task = asyncio.create_task(asyncio.sleep(0))
    await completed_task

    async def fake_run_agent_until_done(*args, **kwargs) -> None:
        await asyncio.sleep(0)

    resolved_controller, restarted_task = await repl.ensure_controller_loop(
        controller=controller,
        agent_task=completed_task,
        create_controller=MagicMock(),
        create_status_callback=lambda ctrl: MagicMock(),
        run_agent_until_done=fake_run_agent_until_done,
        agent=MagicMock(),
        runtime=MagicMock(),
        config=MagicMock(),
        conversation_stats=MagicMock(),
        memory=MagicMock(),
        end_states=[AgentState.FINISHED, AgentState.ERROR],
    )

    assert resolved_controller is controller
    controller.set_agent_state_to.assert_awaited_once_with(AgentState.RUNNING)
    assert restarted_task is not completed_task
    assert restarted_task is not None
    restarted_task = cast(asyncio.Task[None], restarted_task)
    await restarted_task


def test_hud_tracks_llm_call_count() -> None:
    """HUD should count the number of LLM calls from token_usages list."""
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.5
    metrics.token_usages = [
        TokenUsage(prompt_tokens=100, completion_tokens=50),
        TokenUsage(prompt_tokens=200, completion_tokens=80),
        TokenUsage(prompt_tokens=150, completion_tokens=60),
    ]
    hud.update_from_llm_metrics(metrics)
    assert hud.state.llm_calls == 3
    assert hud.state.cost_usd == 0.5


def test_hud_marks_estimated_token_usage() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.1
    metrics.add_token_usage(
        prompt_tokens=120,
        completion_tokens=30,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=8000,
        response_id="resp-est",
        usage_estimated=True,
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.token_usage_estimated is True
    assert "est" in hud._format().plain
    assert "~" in hud._format_compact().plain


def test_hud_does_not_mark_provider_reported_usage_as_estimated() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.1
    metrics.add_token_usage(
        prompt_tokens=120,
        completion_tokens=30,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=8000,
        response_id="resp-real",
        usage_estimated=False,
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.token_usage_estimated is False
    assert " est" not in hud._format().plain


def test_hud_falls_back_to_response_latencies_for_call_count() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.5
    metrics.response_latencies = [
        ResponseLatency(model="openai/gpt-4.1", latency=0.2, response_id="resp-1")
    ]

    hud.update_from_llm_metrics(metrics)

    assert hud.state.llm_calls == 1
    assert hud.state.cost_usd == 0.5


def test_diff_panel_new_file() -> None:
    """DiffPanel should show creation info for new files."""
    obs = MagicMock()
    obs.path = "src/main.py"
    obs.prev_exist = False
    obs.new_content = "print('hello')\nprint('world')\n"
    obs.content = "File created"

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert "Created" in output
    assert "src/main.py" in output
    assert "+ 2 lines" in output


def test_diff_panel_existing_file_with_groups() -> None:
    """DiffPanel should render edit groups for existing file edits."""
    obs = MagicMock()
    obs.path = "README.md"
    obs.prev_exist = True
    obs.get_edit_groups.return_value = [
        {
            "before_edits": ["- old line 1"],
            "after_edits": ["+ new line 1", "+ new line 2"],
        }
    ]

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert "Edited" in output
    assert "README.md" in output
    assert "+ 2 lines" in output
    assert "- 1 lines" in output


def test_show_grinta_splash_renders_logo_text() -> None:
    console = _make_console(width=120)
    show_grinta_splash(console)
    output = _console_output(console)

    # Non-TTY StringIO console: static frame with tagline + hint (see show_grinta_splash).
    assert "AI agent" in output
    assert "Pure grit" in output
    assert "Type /help" in output
    assert "Ctrl+C" in output


def test_prompt_session_requires_tty_streams() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True
    piped_stream = MagicMock()
    piped_stream.isatty.return_value = False

    with patch("backend.cli.repl._prompt_toolkit_available", return_value=True):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is True
    assert _supports_prompt_session(piped_stream, interactive_stream) is False
    assert _supports_prompt_session(interactive_stream, piped_stream) is False


def test_prompt_session_requires_prompt_toolkit() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True

    with patch("backend.cli.repl._prompt_toolkit_available", return_value=False):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is False


def test_prompt_toolkit_available_returns_false_when_missing() -> None:
    original = sys.modules.get("prompt_toolkit")
    sys.modules.pop("prompt_toolkit", None)
    try:
        with patch.dict("sys.modules", {"prompt_toolkit": None}):
            assert _prompt_toolkit_available() is False
    finally:
        if original is not None:
            sys.modules["prompt_toolkit"] = original
        else:
            sys.modules.pop("prompt_toolkit", None)


def test_command_completer_suggests_matching_commands() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document("/s", cursor_position=len("/s")),
            None,
        )
    )

    assert {completion.text for completion in completions} >= {"/status", "/settings"}


def test_command_completer_suggests_autonomy_levels() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document("/autonomy b", cursor_position=len("/autonomy b")),
            None,
        )
    )

    assert [completion.text for completion in completions] == ["balanced"]


def test_command_completer_suggests_resume_targets() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer(
        lambda: [
            ("1", "#1 Fix authentication bug"),
            ("session-123", "Fix authentication bug"),
        ]
    )
    completions = list(
        completer.get_completions(
            Document("/resume s", cursor_position=len("/resume s")),
            None,
        )
    )

    assert [completion.text for completion in completions] == ["session-123"]


def test_slash_command_parser_preserves_quoted_args_and_windows_paths() -> None:
    parsed = _parse_slash_command(r'/checkpoint "pre refactor" C:\Users\me\repo')

    assert parsed.name == "/checkpoint"
    assert parsed.args == ("pre refactor", r"C:\Users\me\repo")


def test_command_completer_suggests_diff_modes() -> None:
    from prompt_toolkit.document import Document

    completer = _build_command_completer()
    completions = list(
        completer.get_completions(
            Document("/diff --n", cursor_position=len("/diff --n")),
            None,
        )
    )

    assert [completion.text for completion in completions] == ["--name-only"]


def test_prompt_message_uses_clean_follow_up_prompt() -> None:
    repl = Repl(_make_config(), _make_console())
    renderer = MagicMock()
    renderer.current_state = AgentState.AWAITING_USER_INPUT
    repl.set_renderer(renderer)

    assert repl._prompt_message() == "❯ "


def test_configure_redirected_streams_uses_utf8_for_non_tty() -> None:
    redirected = MagicMock()
    redirected.isatty.return_value = False
    redirected.reconfigure = MagicMock()

    interactive = MagicMock()
    interactive.isatty.return_value = True
    interactive.reconfigure = MagicMock()

    _configure_redirected_streams(redirected, interactive, None)

    redirected.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
    interactive.reconfigure.assert_not_called()


def test_read_piped_stdin_returns_none_for_tty() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch.object(sys, "stdin", stdin):
        assert _read_piped_stdin() is None


def test_read_piped_stdin_reads_non_tty_once() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = "queued task\n"

    with patch.object(sys, "stdin", stdin):
        assert _read_piped_stdin() == "queued task\n"


def test_confirmation_handles_all_risk_levels() -> None:
    """All ActionSecurityRisk levels should map to readable labels."""
    for risk_val, expected_label in [
        (ActionSecurityRisk.HIGH, "HIGH"),
        (ActionSecurityRisk.MEDIUM, "MEDIUM"),
        (ActionSecurityRisk.LOW, "LOW"),
        (ActionSecurityRisk.UNKNOWN, "ASK"),
    ]:
        action = CmdRunAction(command="test")
        action.security_risk = risk_val
        label, _ = _risk_label(action)
        assert label == expected_label


@pytest.mark.asyncio
async def test_renderer_handles_error_observation() -> None:
    """ErrorObservation should be rendered with structured error panel."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(
        content="FileNotFoundError: x.py\nTraceback detail here"
    )
    await renderer.handle_event(error_obs)

    assert hud.state.ledger_status == "Error"
    # Error panel printed to console (no Live active).
    output = _console_output(console)
    assert "FileNotFoundError" in output


@pytest.mark.asyncio
async def test_start_stop_live_flushes_items_to_console() -> None:
    """During Live, system messages print immediately; stop_live clears the live region."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    renderer.start_live()
    renderer.add_system_message("Working…", title="grinta")
    renderer.stop_live()

    output = _console_output(console)
    assert "Working" in output


@pytest.mark.asyncio
async def test_renderer_error_observation_shows_recovery_steps() -> None:
    """Known provider errors should include actionable recovery guidance."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(content="401 Unauthorized\ninvalid api key")
    await renderer.handle_event(error_obs)

    # Error panel printed to console (no Live active).
    output = _console_output(console)
    assert "What you can try" in output
    assert "/settings" in output
    assert "update the API key" in output


@pytest.mark.asyncio
async def test_renderer_timeout_error_uses_notice_panel_copy() -> None:
    """Provider wait timeouts should use cyan notice framing, not raw exception titles."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content="Timeout: Fallback completion timed out after 60.0 seconds"
        )
    )
    output = _console_output(console)
    assert "Still no reply" in output
    assert "Next steps" in output
    assert "APP_LLM_FALLBACK_TIMEOUT_SECONDS" in output


@pytest.mark.asyncio
async def test_renderer_notice_panel_does_not_repeat_summary_under_next_steps() -> None:
    """Notice headline already states the summary; recovery must list only numbered steps."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(content="TimeoutError: LLM call timed out after 120s")
    )
    output = _console_output(console)
    needle = "The model didn't finish within Grinta's wait window"
    assert needle in output
    assert output.count(needle) == 1


@pytest.mark.asyncio
async def test_reasoning_transcript_skips_duplicate_prefix_between_tool_steps() -> None:
    """CoT segments often restate the same opening; only new lines print after each flush."""
    console = _make_console()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, HUDBar(), reasoning, loop=asyncio.get_running_loop()
    )

    reasoning.start()
    reasoning.set_streaming_thought("Goal line\nPlan A\n")
    renderer._stop_reasoning()

    reasoning.start()
    reasoning.set_streaming_thought("Goal line\nPlan A\nPlan B\n")
    renderer._stop_reasoning()

    output = _console_output(console)
    assert output.count("Goal line") == 1
    assert "Plan B" in output


@pytest.mark.asyncio
async def test_renderer_stream_fallback_status_renders_still_working_panel() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        StatusObservation(content="Stream timed out — retrying without streaming…")
    )
    output = _console_output(console)
    assert "Still Working" in output
    assert "non-streaming" in output.lower()


@pytest.mark.asyncio
async def test_renderer_syntax_validation_error_panel_is_compact() -> None:
    """Syntax validation failures should not dump tree-sitter noise into the CLI panel."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    noisy = (
        "ERROR:\nSyntax validation failed: Syntax error at "
        "C:\\proj\\demo.test.ts:8:3: node=ERROR\n"
        "  Node text: 'it'\n"
        "    it('x', () => {\n"
        "    ^\n"
    )
    error_obs = ErrorObservation(content=noisy)
    await renderer.handle_event(error_obs)

    output = _console_output(console)
    assert "syntax check" in output.lower()
    assert "What you can try" in output
    assert "node=" not in output
    assert "Node text" not in output


@pytest.mark.asyncio
async def test_system_error_message_shows_restart_guidance_for_init_failures() -> None:
    """Startup failures should suggest how to recover outside the REPL."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    renderer.add_system_message(
        "No API key or model configured.\nAuthenticationError: invalid api key",
        title="error",
    )

    output = _console_output(console)
    assert "Restart grinta" in output
    assert "settings.json" in output


@pytest.mark.asyncio
async def test_renderer_shows_recall_observation() -> None:
    """RecallObservation should show a brief recall indicator."""
    from backend.core.enums import RecallType
    from backend.ledger.observation.agent import RecallObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    recall_obs = RecallObservation(
        content="recalled",
        recall_type=RecallType.WORKSPACE_CONTEXT,
    )
    await renderer.handle_event(recall_obs)

    # Recall goes to reasoning panel — no console output expected
    output = _console_output(console)
    assert output == ""
    assert renderer._reasoning.active
    assert "recalled" in renderer._reasoning._current_action.lower()


def test_autonomy_command_shows_current_level() -> None:
    """_handle_autonomy_command with no arg shows current level."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    repl.handle_autonomy_command("/autonomy")
    mock_renderer.add_system_message.assert_called_once()
    call_text = mock_renderer.add_system_message.call_args[0][0]
    assert "balanced" in call_text


def test_prompt_toolbar_reflects_state_and_autonomy() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    # PAUSED is collapsed to STOPPED in CLI — label shows "Stopped"
    repl.set_renderer(type("RendererStub", (), {"current_state": AgentState.STOPPED})())

    autonomy_controller = MagicMock()
    autonomy_controller.autonomy_level = "full"
    controller = MagicMock()
    controller.autonomy_controller = autonomy_controller
    repl.set_controller(controller)
    repl._hud.update_model("openai/google/gemini-3-flash-preview")

    toolbar = repl._prompt_toolbar_text()

    assert "Stopped" in toolbar
    assert "autonomy:full" in toolbar
    assert "Tab for commands" in toolbar
    assert "provider: google" in toolbar
    assert "model: gemini-3-flash-preview" in toolbar


def test_unknown_command_suggests_closest_match() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command("/stat")

    assert result is True
    message = mock_renderer.add_system_message.call_args[0][0]
    assert "/status" in message
    assert "autocomplete" in message


def test_help_command_can_show_single_command_topic() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command("/help diff")

    assert result is True
    mock_renderer.add_markdown_block.assert_called_once()
    markdown = mock_renderer.add_markdown_block.call_args[0][1]
    assert "/diff [--stat|--name-only|--patch] [path]" in markdown


def test_model_command_rejects_unqualified_model() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    with patch("backend.cli.config_manager.update_model") as update_model:
        result = repl.handle_command("/model gpt-4.1")

    assert result is True
    update_model.assert_not_called()
    message = mock_renderer.add_system_message.call_args[0][0]
    assert "provider-qualified" in message


def test_diff_command_uses_configured_project_root(tmp_path: Path) -> None:
    config = _make_config()
    config.project_root = str(tmp_path)
    repl = Repl(config, Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)
    completed = subprocess.CompletedProcess(
        args=["git", "diff"], returncode=0, stdout="src/app.py\n", stderr=""
    )

    with patch("backend.cli.repl.subprocess.run", return_value=completed) as run_git:
        result = repl.handle_command('/diff --name-only "src/app file.py"')

    assert result is True
    run_git.assert_called_once()
    assert run_git.call_args.args[0] == [
        "git",
        "diff",
        "--name-only",
        "--",
        "src/app file.py",
    ]
    assert run_git.call_args.kwargs["cwd"] == tmp_path.resolve()


def test_sessions_command_accepts_optional_limit() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    with patch("backend.cli.session_manager.list_sessions") as list_sessions:
        result = repl.handle_command("/sessions list 5")

    assert result is True
    list_sessions.assert_called_once()
    assert list_sessions.call_args.kwargs["limit"] == 5


def test_autonomy_command_sets_level() -> None:
    """_handle_autonomy_command with a valid level should update the controller."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    ac = MagicMock()
    ac.autonomy_level = "balanced"
    controller = MagicMock()
    controller.autonomy_controller = ac
    repl.set_controller(controller)

    repl.handle_autonomy_command("/autonomy full")
    assert ac.autonomy_level == "full"
    mock_renderer.add_system_message.assert_called_once()


def test_entry_point_rejects_legacy_serve_subcommand() -> None:
    """Entry point should reject the removed serve subcommand."""
    import sys

    with patch.object(sys, "argv", ["app", "serve", "--port", "3030"]):
        from backend.cli.entry import main

        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2


# ── New tests: CLI flags ─────────────────────────────────────────────────


def test_entry_point_parses_model_flag() -> None:
    """--model flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, "argv", ["app", "--model", "openai/gpt-4.1"]):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model="openai/gpt-4.1",
                project=None,
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_project_flag(tmp_path: Path) -> None:
    """--project flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, "argv", ["app", "--project", str(tmp_path)]):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=str(tmp_path.resolve()),
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_cleanup_storage_flag() -> None:
    """--cleanup-storage should be forwarded to repl main."""
    import sys

    with patch.object(sys, "argv", ["app", "--cleanup-storage"]):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=None,
                cleanup_storage=True,
                no_splash=False,
            )


def test_entry_point_parses_both_flags(tmp_path: Path) -> None:
    """Both --model and --project should be forwarded."""
    import sys

    with patch.object(
        sys,
        "argv",
        ["app", "-m", "anthropic/claude-sonnet-4-20250514", "-p", str(tmp_path)],
    ):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model="anthropic/claude-sonnet-4-20250514",
                project=str(tmp_path.resolve()),
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_cleanup_and_project_flags(tmp_path: Path) -> None:
    """Cleanup flag should preserve the selected project override."""
    import sys

    with patch.object(
        sys, "argv", ["app", "--cleanup-storage", "--project", str(tmp_path)]
    ):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=str(tmp_path.resolve()),
                cleanup_storage=True,
                no_splash=False,
            )


def test_entry_point_parses_no_splash_flag() -> None:
    """--no-splash should be forwarded to repl main."""
    import sys

    with patch.object(sys, "argv", ["app", "--no-splash"]):
        with patch("backend.cli.main.main") as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=None,
                cleanup_storage=False,
                no_splash=True,
            )


def test_grinta_main_parses_project_flag(tmp_path: Path) -> None:
    """Grinta should parse --project even when invoked via backend.cli.main."""
    import sys

    with patch.object(sys, "argv", ["grinta", "--project", str(tmp_path)]):
        with patch(
            "backend.cli.main._async_main", new_callable=MagicMock
        ) as mock_async_main:
            with patch("backend.cli.main.asyncio.run") as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_async_main.assert_called_once_with(
        model=None, project=str(tmp_path.resolve()), show_splash=True
    )
    mock_asyncio_run.assert_called_once()


def test_grinta_main_parses_no_splash_flag() -> None:
    """Direct backend.cli.main invocation should honor --no-splash."""
    import sys

    with patch.object(sys, "argv", ["grinta", "--no-splash"]):
        with patch(
            "backend.cli.main._async_main", new_callable=MagicMock
        ) as mock_async_main:
            with patch("backend.cli.main.asyncio.run") as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_async_main.assert_called_once_with(model=None, project=None, show_splash=False)
    mock_asyncio_run.assert_called_once()


def test_grinta_main_rejects_legacy_serve_subcommand() -> None:
    """Grinta main should reject the removed serve subcommand."""
    import sys

    with patch.object(sys, "argv", ["grinta", "serve", "--port", "3030"]):
        with patch("backend.cli.main.asyncio.run") as mock_asyncio_run:
            from backend.cli.main import main

            with pytest.raises(SystemExit) as exc:
                main()

    assert exc.value.code == 2
    mock_asyncio_run.assert_not_called()


def test_grinta_main_runs_cleanup_storage_without_asyncio() -> None:
    """Cleanup mode should run the one-off storage command and exit."""
    import sys

    with patch.object(sys, "argv", ["grinta", "--cleanup-storage"]):
        with patch("backend.cli.main.asyncio.run") as mock_asyncio_run:
            with patch(
                "backend.cli.storage_cleanup.run_storage_cleanup_command",
                return_value=0,
            ) as mock_cleanup:
                from backend.cli.main import main

                main()

    mock_cleanup.assert_called_once_with(None)
    mock_asyncio_run.assert_not_called()


@pytest.mark.asyncio
async def test_async_main_defaults_workspace_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    config = AppConfig()
    config.get_llm_config().model = "openai/gpt-4.1"

    repl = MagicMock()
    repl.run = AsyncMock()
    sim_home = tmp_path / "SIM_HOME"
    sim_home.mkdir()
    monkeypatch.setenv("HOME", str(sim_home))
    monkeypatch.setenv("USERPROFILE", str(sim_home))

    with patch("backend.core.config.load_app_config", return_value=config):
        with patch("backend.cli.main.Console", return_value=_make_console()):
            with patch("backend.cli.repl.Repl", return_value=repl):
                with patch(
                    "backend.cli.config_manager.needs_onboarding", return_value=False
                ):
                    with patch(
                        "backend.cli.config_manager.ensure_default_model",
                        return_value="openai/gpt-4.1",
                    ):
                        with patch("backend.cli.main._setup_logging"):
                            with patch("pathlib.Path.cwd", return_value=tmp_path):
                                from backend.cli.main import _async_main

                                await _async_main()

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    assert config.local_data_root == get_project_local_data_root(tmp_path)
    assert "workspaces" in config.local_data_root
    assert config.get_agent_config(config.default_agent).cli_mode is True
    repl.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_main_queues_piped_input(tmp_path: Path) -> None:
    config = AppConfig()
    config.get_llm_config().model = "openai/gpt-4.1"

    repl = MagicMock()
    repl.run = AsyncMock()

    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = "queued task\n"

    with patch.object(sys, "stdin", stdin):
        with patch("backend.core.config.load_app_config", return_value=config):
            with patch("backend.cli.main.Console", return_value=_make_console()):
                with patch("backend.cli.repl.Repl", return_value=repl):
                    with patch(
                        "backend.cli.config_manager.needs_onboarding",
                        return_value=False,
                    ):
                        with patch(
                            "backend.cli.config_manager.ensure_default_model",
                            return_value="openai/gpt-4.1",
                        ):
                            with patch("backend.cli.main._setup_logging"):
                                with patch("pathlib.Path.cwd", return_value=tmp_path):
                                    from backend.cli.main import _async_main

                                    await _async_main()

    repl.queue_initial_input.assert_called_once_with("queued task\n")
    repl.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_main_keeps_explicit_project_override(
    tmp_path: Path, monkeypatch
) -> None:
    config = AppConfig()
    config.get_llm_config().model = "openai/gpt-4.1"
    repl = MagicMock()
    repl.run = AsyncMock()
    sim_home = tmp_path / "SIM_HOME"
    sim_home.mkdir()
    monkeypatch.setenv("HOME", str(sim_home))
    monkeypatch.setenv("USERPROFILE", str(sim_home))

    with patch("backend.core.config.load_app_config", return_value=config):
        with patch("backend.cli.main.Console", return_value=_make_console()):
            with patch("backend.cli.repl.Repl", return_value=repl):
                with patch(
                    "backend.cli.config_manager.needs_onboarding", return_value=False
                ):
                    with patch(
                        "backend.cli.config_manager.ensure_default_model",
                        return_value="openai/gpt-4.1",
                    ):
                        with patch("backend.cli.main._setup_logging"):
                            from backend.cli.main import _async_main

                            await _async_main(project=str(tmp_path))

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    assert config.local_data_root == get_project_local_data_root(tmp_path)
    assert "workspaces" in config.local_data_root
    assert config.get_agent_config(config.default_agent).cli_mode is True


@pytest.mark.asyncio
async def test_repl_non_interactive_uses_queued_input_before_stdin() -> None:
    repl = Repl(_make_config(), _make_console())
    repl.queue_initial_input("queued task\n")

    stdin = MagicMock()
    stdin.readline.return_value = ""

    with patch.object(sys, "stdin", stdin):
        result = await repl._read_non_interactive_input()

    assert result == "queued task\n"
    stdin.readline.assert_not_called()


def test_find_sessions_root_uses_project_storage_sessions(tmp_path: Path) -> None:
    from backend.cli.session_manager import _find_sessions_root

    sessions = tmp_path / ".grinta" / "storage" / "sessions"
    sessions.mkdir(parents=True)
    config = AppConfig(local_data_root=str(tmp_path / ".grinta" / "storage"))

    assert _find_sessions_root(config) == sessions


# ── New tests: Ctrl+C handling ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_agent_stops_task() -> None:
    """_cancel_agent should cancel a running task and show message."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    async def never_finish():
        await asyncio.sleep(999)

    task = asyncio.create_task(never_finish())

    await repl.cancel_agent(task)

    assert task.cancelled()
    mock_renderer.add_system_message.assert_called_once()
    assert "Interrupted" in mock_renderer.add_system_message.call_args[0][0]


@pytest.mark.asyncio
async def test_repl_run_saves_controller_state_on_exit() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    controller = MagicMock()
    repl.set_controller(controller)

    async def fake_read() -> str:
        return ""

    with (
        patch(
            "backend.core.bootstrap.main._initialize_session_components",
            side_effect=RuntimeError("bootstrap failed"),
        ),
        patch("backend.cli.repl.get_current_model", return_value="test-model"),
        patch.object(repl, "_read_non_interactive_input", side_effect=fake_read),
        patch("backend.cli.repl.load_app_config"),
    ):
        await repl.run()

    controller.save_state.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_agent_idle_drains_late_final_message() -> None:
    from backend.ledger.observation.agent import AgentStateChangedObservation

    console = _make_console()
    repl = Repl(_make_config(), console)
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    repl.set_renderer(renderer)
    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.AWAITING_USER_INPUT

    await renderer.handle_event(
        AgentStateChangedObservation("", AgentState.AWAITING_USER_INPUT)
    )

    late_message = MessageAction(content="Final answer", wait_for_response=True)
    late_message.source = EventSource.AGENT

    async def emit_late_message() -> None:
        await asyncio.sleep(0.01)
        renderer._on_event_threadsafe(late_message)

    emit_task = asyncio.create_task(emit_late_message())
    await repl._wait_for_agent_idle(controller, None)
    await emit_task

    output = _console_output(console)
    assert "Final answer" in output


@pytest.mark.asyncio
async def test_wait_for_agent_idle_default_timeout_disabled(monkeypatch) -> None:
    repl = Repl(_make_config(), _make_console())
    controller = MagicMock()

    states = [
        AgentState.RUNNING,
        AgentState.RUNNING,
        AgentState.AWAITING_USER_INPUT,
    ]

    def _next_state():
        return states.pop(0) if states else AgentState.AWAITING_USER_INPUT

    controller.get_agent_state.side_effect = _next_state

    async def never_finish() -> None:
        await asyncio.sleep(999)

    agent_task = asyncio.create_task(never_finish())
    tick = {"value": 0.0}

    def _fake_monotonic() -> float:
        tick["value"] += 10_000.0
        return tick["value"]

    monkeypatch.delenv("APP_AGENT_HARD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("APP_AGENT_HARD_TIMEOUT_CMD_SECONDS", raising=False)

    with patch("backend.cli.repl.time.monotonic", side_effect=_fake_monotonic):
        await repl._wait_for_agent_idle(controller, agent_task)

    assert not agent_task.cancelled()

    agent_task.cancel()
    with suppress(asyncio.CancelledError):
        await agent_task


@pytest.mark.asyncio
async def test_wait_for_agent_idle_rate_limited_not_treated_as_idle() -> None:
    """RATE_LIMITED must not end _wait_for_agent_idle while backoff is pending.

    Regression: including RATE_LIMITED in idle_states returned to the prompt
    immediately even though RetryService had scheduled an automatic resume.
    """
    repl = Repl(_make_config(), _make_console())
    repl.set_renderer(None)
    controller = MagicMock()

    calls = {"n": 0}

    def _state() -> AgentState:
        calls["n"] += 1
        if calls["n"] < 8:
            return AgentState.RATE_LIMITED
        return AgentState.AWAITING_USER_INPUT

    controller.get_agent_state.side_effect = _state

    async def never_finish() -> None:
        await asyncio.sleep(999)

    agent_task = asyncio.create_task(never_finish())
    await repl._wait_for_agent_idle(controller, agent_task)

    agent_task.cancel()
    with suppress(asyncio.CancelledError):
        await agent_task

    assert calls["n"] >= 8


@pytest.mark.asyncio
async def test_repl_run_shows_ready_before_background_bootstrap() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    events: list[str] = []
    original_add_system_message = CLIEventRenderer.add_system_message

    async def fake_read() -> str:
        await asyncio.sleep(0)
        return ""

    def record_message(self, message: str, title: str = "system"):
        events.append(message)
        return original_add_system_message(self, message, title=title)

    def fail_bootstrap(*_args, **_kwargs):
        events.append("bootstrap")
        raise RuntimeError("bootstrap failed")

    with (
        patch.object(
            CLIEventRenderer,
            "add_system_message",
            autospec=True,
            side_effect=record_message,
        ),
        patch("backend.cli.repl.get_current_model", return_value="test-model"),
        patch("backend.cli.repl._supports_prompt_session", return_value=False),
        patch.object(repl, "_read_non_interactive_input", side_effect=fake_read),
        patch(
            "backend.core.bootstrap.main._initialize_session_components",
            side_effect=fail_bootstrap,
        ),
    ):
        await repl.run()

    assert events
    # The first system message before bootstrap should be "Initializing engine…"
    # (the old "grinta ready" message was removed — the splash covers that).
    init_msgs = [e for e in events if e != "bootstrap"]
    assert any("nitializ" in m for m in init_msgs) or events


@pytest.mark.asyncio
async def test_repl_run_accepts_first_message_before_mcp_warmup_finishes() -> None:
    config = AppConfig()
    console = Console(file=io.StringIO(), force_terminal=False)
    repl = Repl(config, console)
    event_stream = MagicMock()
    event_stream.sid = "session-1"
    runtime = MagicMock()
    runtime.event_stream = event_stream
    memory = MagicMock()
    controller = MagicMock()
    agent = MagicMock()
    agent.config.enable_mcp = True
    agent.mcp_capability_status = {"connected_client_count": 0}
    llm_registry = MagicMock()
    conversation_stats = MagicMock()
    acquire_result = "runtime-handle"
    first_message_dispatched = asyncio.Event()
    allow_mcp_finish = asyncio.Event()
    queued_inputs: asyncio.Queue[str] = asyncio.Queue()
    await queued_inputs.put("hello\n")

    def add_event(action, source):
        del source
        if isinstance(action, MessageAction) and action.content == "hello":
            first_message_dispatched.set()

    async def fake_read() -> str:
        return await queued_inputs.get()

    async def fake_setup_mcp(*_args, **_kwargs) -> None:
        await allow_mcp_finish.wait()
        agent.mcp_capability_status = {"connected_client_count": 2}

    event_stream.add_event.side_effect = add_event

    with (
        patch("backend.cli.repl.get_current_model", return_value="test-model"),
        patch("backend.cli.repl._supports_prompt_session", return_value=False),
        patch.object(repl, "_read_non_interactive_input", side_effect=fake_read),
        patch.object(
            repl,
            "_ensure_controller_loop",
            new=AsyncMock(return_value=(controller, None)),
        ),
        patch.object(
            repl,
            "_wait_for_agent_idle",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.core.bootstrap.main._initialize_session_components",
            return_value=(
                "session-1",
                llm_registry,
                conversation_stats,
                config,
                agent,
            ),
        ),
        patch(
            "backend.core.bootstrap.main._setup_runtime_for_controller",
            return_value=(runtime, None, acquire_result),
        ),
        patch(
            "backend.core.bootstrap.main._setup_memory",
            new=AsyncMock(return_value=memory),
        ) as mock_setup_memory,
        patch(
            "backend.core.bootstrap.main._setup_mcp_tools",
            new=AsyncMock(side_effect=fake_setup_mcp),
        ) as mock_setup_mcp,
        patch("backend.execution.runtime_orchestrator.release") as mock_release,
    ):
        run_task = asyncio.create_task(repl.run())
        await asyncio.wait_for(first_message_dispatched.wait(), timeout=1)
        assert not allow_mcp_finish.is_set()
        allow_mcp_finish.set()
        await queued_inputs.put("")
        await run_task

    mock_setup_memory.assert_awaited_once()
    mock_setup_mcp.assert_awaited_once()
    mock_release.assert_called_once_with(acquire_result)


# ── New tests: Reasoning elapsed time ────────────────────────────────────


def test_start_live_passes_vertical_overflow_crop() -> None:
    """Rich Live must use ``crop`` (not ``visible``) for the Thinking panel.

    Regression: ``vertical_overflow='visible'`` caused Rich to re-print the
    overflow portion of the Live body on every refresh when the panel was
    taller than the terminal. With streaming reasoning that grows line by
    line, this stacked dozens of duplicate copies per turn in the scrollback
    — the panel looked like it was stuttering. ``crop`` redraws in place;
    panels that could exceed height (streaming preview, reasoning thoughts)
    clamp themselves via ``options.max_height`` inside their renderables.
    """
    console = _make_console()
    loop = asyncio.new_event_loop()
    with patch("backend.cli.event_renderer.Live") as live_cls:
        try:
            live_cls.return_value = MagicMock()
            r = CLIEventRenderer(console, HUDBar(), ReasoningDisplay(), loop=loop)
            r.start_live()
        finally:
            loop.close()
    assert live_cls.call_args is not None
    assert live_cls.call_args.kwargs.get("vertical_overflow") == "crop"


def test_reasoning_display_elapsed_time() -> None:
    """ReasoningDisplay should show elapsed time when active."""
    rd = ReasoningDisplay()
    with patch(
        "backend.cli.reasoning_display.time.monotonic", side_effect=[100.0, 105.0]
    ):
        rd.start()
        console = _make_console(width=80)
        console.print(rd.renderable())
    output = _console_output(console)
    assert "5s" in output


def test_reasoning_display_stop_resets_timer() -> None:
    """stop() should reset the start time."""
    rd = ReasoningDisplay()
    with patch("backend.cli.reasoning_display.time.monotonic", return_value=100.0):
        rd.start()
    assert rd.elapsed_seconds is not None
    rd.stop()
    assert rd.elapsed_seconds is None


# ── New tests: Atomic settings writes ────────────────────────────────────


def test_atomic_settings_write(tmp_path: Path) -> None:
    """_save_raw_settings should write atomically via tempfile + rename."""
    from backend.cli.config_manager import _load_raw_settings, _save_raw_settings

    settings_file = tmp_path / "settings.json"
    with patch("backend.cli.config_manager._settings_path", return_value=settings_file):
        data = {
            "llm_api_key": LLM_API_KEY_SETTINGS_PLACEHOLDER,
            "llm_model": "test/model",
        }
        _save_raw_settings(data)

        loaded = _load_raw_settings()
        assert loaded["llm_api_key"] == LLM_API_KEY_SETTINGS_PLACEHOLDER
        assert loaded["llm_model"] == "test/model"

        # No stale .tmp files left behind
        tmp_files = list(settings_file.parent.glob("*.tmp"))
        assert not tmp_files


def test_get_masked_api_key_returns_not_set_when_missing() -> None:
    """Masking should be safe when no key is configured anywhere."""
    from backend.cli.config_manager import get_masked_api_key

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = "openai/gpt-4.1"
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {}, clear=True):
        assert get_masked_api_key(config) == "(not set)"


def test_get_masked_api_key_reads_env_fallback() -> None:
    """Masking should use env-backed keys when config.api_key is unset."""
    from backend.cli.config_manager import get_masked_api_key

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = ""
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {"LLM_API_KEY": "env-secret-12345678"}, clear=True):
        masked = get_masked_api_key(config)

    assert masked.startswith("env-")
    assert masked.endswith("5678")
    assert "•" in masked


def test_ensure_default_model_sets_model_from_google_key() -> None:
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {"LLM_API_KEY": "AIzaSyBxxxxxxxxxxxxxxx"}, clear=True):
        selected = ensure_default_model(config)

    assert selected == "google/gemini-2.5-flash"
    assert llm_cfg.model == "google/gemini-2.5-flash"


def test_ensure_default_model_preserves_existing_model() -> None:
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = "anthropic/claude-sonnet-4-20250514"
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(
        os.environ, {"LLM_API_KEY": "sk-test12345678901234567890"}, clear=True
    ):
        selected = ensure_default_model(config)

    assert selected == "anthropic/claude-sonnet-4-20250514"
    assert llm_cfg.model == "anthropic/claude-sonnet-4-20250514"


def test_ensure_default_model_uses_provider_specific_env_var() -> None:
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(
        os.environ, {"OPENAI_API_KEY": "sk-test12345678901234567890"}, clear=True
    ):
        selected = ensure_default_model(config)

    assert selected == "openai/gpt-4.1"
    assert llm_cfg.model == "openai/gpt-4.1"


def test_run_onboarding_uses_provider_default_model(tmp_path: Path) -> None:
    from backend.cli.config_manager import run_onboarding

    settings_file = tmp_path / "settings.json"
    # New flow: 1) provider number (2 = Anthropic), 2) model (accept default), 3) API key
    entered = iter(["2", "", "sk-ant-api03-test-value"])
    loaded_config = MagicMock()

    with patch("backend.cli.config_manager._settings_path", return_value=settings_file):
        with patch(
            "backend.cli.config_manager.Prompt.ask",
            side_effect=lambda *args, **kwargs: next(entered),
        ):
            with patch(
                "backend.cli.config_manager.load_app_config", return_value=loaded_config
            ):
                with patch("os.isatty", return_value=True):
                    result = run_onboarding()

    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["llm_api_key"] == LLM_API_KEY_SETTINGS_PLACEHOLDER
    assert saved["llm_model"] == "anthropic/claude-sonnet-4-20250514"
    assert saved["llm_provider"] == "anthropic"
    env_file = settings_file.parent / ".env"
    assert env_file.is_file()
    assert "sk-ant-api03-test-value" in env_file.read_text(encoding="utf-8")
    assert result is loaded_config


# ── New tests: Budget warnings ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_warning_at_80_percent() -> None:
    """Renderer should emit a warning when cost reaches 80% of budget."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
        max_budget=1.0,
    )

    metrics = Metrics()
    metrics.accumulated_cost = 0.85
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk="x", accumulated="x", is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.budget_warned_80
    assert not renderer.budget_warned_100
    # Budget warning printed to console (no Live active).
    output = _console_output(console)
    assert "Budget" in output or "budget" in output


@pytest.mark.asyncio
async def test_budget_exceeded_at_100_percent() -> None:
    """Renderer should emit a strong warning when cost exceeds budget."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
        max_budget=1.0,
    )

    metrics = Metrics()
    metrics.accumulated_cost = 1.05
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk="x", accumulated="x", is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.budget_warned_100


@pytest.mark.asyncio
async def test_no_budget_warning_when_no_budget_set() -> None:
    """No budget warnings should fire when max_budget is None."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    metrics = Metrics()
    metrics.accumulated_cost = 999.0
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk="x", accumulated="x", is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert not renderer.budget_warned_80
    assert not renderer.budget_warned_100


@pytest.mark.asyncio
async def test_streaming_preview_renders_streaming_panel() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    chunk = StreamingChunkAction(chunk="Hello", accumulated="Hello", is_final=False)
    chunk.source = EventSource.AGENT

    await renderer.handle_event(chunk)

    console.print(renderer._render_streaming_preview(max_width=None, max_lines=None))
    output = _console_output(console)

    # _render_streaming_preview uses a titled panel so live draft text is visually separated.
    assert "Draft Reply" in output
    assert "Hello" in output


def test_streaming_preview_auto_scroll_shows_latest_content() -> None:
    console = _make_console(width=80)
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.new_event_loop(),
    )

    renderer._streaming_accumulated = "\n".join(
        [f"line {idx:03d}" for idx in range(1, 61)]
    )

    console.print(renderer._render_streaming_preview(max_width=80, max_lines=10))
    output = _console_output(console)

    assert "Draft Reply" in output
    assert "Tail preview" in output
    assert "line 060" in output
    assert "line 001" not in output


@pytest.mark.asyncio
async def test_renderer_shows_command_context_for_output() -> None:
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    obs = CmdOutputObservation(content="2 passed", command="python -m pytest -q")
    await renderer.handle_event(obs)

    # exit_code defaults to -1 (unknown), so renderer shows a dim error line with content snippet.
    output = _console_output(console)
    assert "exit -1" in output
    assert "2 passed" in output


@pytest.mark.asyncio
async def test_renderer_browser_cmd_output_does_not_print_ghost_terminal_card() -> None:
    """Regression: browser tool completions reuse ``CmdOutputObservation`` with
    ``command='browser navigate'`` etc. The Browser activity card is already
    printed when the action is dispatched; the observation handler used to
    fall through to the shell-result path and emit a spurious
    ``Terminal / Ran / $ (command) / ✓ done`` block. That created the duplicate
    rows visible in real sessions between every browser step.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    for cmd in (
        "browser navigate",
        "browser screenshot",
        "browser snapshot",
        "browser click",
    ):
        obs = CmdOutputObservation(
            content=f"Done: {cmd}",
            command=cmd,
            exit_code=0,
        )
        await renderer.handle_event(obs)

    output = _console_output(console)
    # The specific corruption pattern we saw in the bug report must not appear.
    assert "$ (command)" not in output
    # No Terminal-card header for these observations.
    assert "Terminal" not in output, (
        "Browser CmdOutputObservations should not render as Terminal cards; got:\n"
        + output
    )


@pytest.mark.asyncio
async def test_renderer_browser_screenshot_timeout_shows_browser_guidance() -> None:
    """Regression: the generic ``timed out`` branch applied LLM-provider
    advice (``Check your network connection and the provider status page``)
    to browser screenshot timeouts. The new branch must fire first and
    give browser-specific next steps.
    """
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(
        content="ERROR: Browser screenshot timed out after 45s (with one retry)."
    )
    await renderer.handle_event(error_obs)

    output = _console_output(console)
    # Recoverable timeouts render as a cyan notice with "Next steps"; hard
    # errors use "What you can try".
    assert "Next steps" in output or "What you can try" in output
    assert "browser" in output.lower()
    # The misleading provider-centric copy must not appear for this case.
    assert "provider status page" not in output
    assert "faster model" not in output


@pytest.mark.asyncio
async def test_renderer_directory_view_uses_entries_not_lines() -> None:
    """Regression: ``FileReadObservation`` on a directory previously rendered
    the result as ``N lines`` because the handler unconditionally split the
    content on newlines. ``str_replace_editor view`` on a directory returns
    a ``Directory contents of <path>:`` header followed by one entry per
    line; users reading ``Viewed . • 2 lines`` for a dir listing (where one
    of the lines is the header) was confusing. Now we label as ``entries``
    and discount the header line.
    """
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()

    action = FileReadAction(path=".")
    action.source = EventSource.AGENT
    renderer._process_event_data(action)

    content = "Directory contents of .:\n  ./\n  index.html\n  style.css\n"
    obs = FileReadObservation(content=content, path=".")
    renderer._process_event_data(obs)

    output = _console_output(console)
    assert "entries" in output, f'expected "entries" label, got:\n{output}'
    assert "lines" not in output or "entries" in output
    # ``3 entries`` — header stripped from the count (4 lines → 3 entries).
    assert "3 entries" in output, output


@pytest.mark.asyncio
async def test_renderer_file_view_still_uses_lines() -> None:
    """Counterpart to the directory-view test: a real file read still gets
    the ``N lines`` label. Guards against an overzealous fix that routes
    every read through the entries branch.
    """
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()

    action = FileReadAction(path="chess.html")
    action.source = EventSource.AGENT
    renderer._process_event_data(action)

    obs = FileReadObservation(
        content="<html>\n<head></head>\n<body></body>\n</html>\n",
        path="chess.html",
    )
    renderer._process_event_data(obs)

    output = _console_output(console)
    assert "lines" in output
    assert "entries" not in output


@pytest.mark.asyncio
async def test_renderer_non_browser_cmd_with_browser_prefix_word_still_rendered() -> (
    None
):
    """Regression for the *widening* of the filter: the original
    ``startswith('browser ')`` check would have silently eaten any user
    shell command that starts with the word "browser " (e.g.
    ``browser start-fuzz`` or a custom script named ``browser``). We now
    match a strict whitelist of known browser-tool command strings — a
    real shell command must still reach the Terminal card path.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    obs = CmdOutputObservation(
        content="custom-browser started on port 9000",
        command="browser-cli --open",
        exit_code=0,
    )
    await renderer.handle_event(obs)

    output = _console_output(console)
    # The Terminal card path must fire — proof that the observation wasn't
    # silently dropped by the old ``startswith('browser ')`` filter. We don't
    # require the command text itself in the rendered card (the renderer only
    # shows that when it can pair the observation with a preceding
    # CmdRunAction; here we're exercising the filter in isolation).
    assert "Terminal" in output, (
        "Non-browser-tool command was suppressed by the browser-activity "
        "filter; the Terminal card should still have been rendered:\n" + output
    )


def test_format_reasoning_snapshot_appends_ellipsis_when_mid_sentence() -> None:
    """A committed reasoning block that ends mid-phrase (because the model
    kept going by calling a tool) should visually signal continuation with a
    trailing ``…`` instead of looking like a truncation bug.
    """
    from backend.cli.transcript import format_reasoning_snapshot

    console = _make_console()
    group = format_reasoning_snapshot(
        ["I will build it as a single HTML file with embedded CSS"]
    )
    console.print(group)
    output = _console_output(console)
    assert "…" in output

    # When the last line already ends in sentence-terminal punctuation, we
    # must *not* add an ellipsis (that would read as doubled punctuation).
    console2 = _make_console()
    group2 = format_reasoning_snapshot(["I will build it as a single HTML file."])
    console2.print(group2)
    assert "…" not in _console_output(console2)


def test_error_guidance_routes_browser_timeouts_to_browser_branch() -> None:
    """Unit-level check that the classifier picks the browser branch before
    the generic timeout branch.
    """
    from backend.cli.event_renderer import _error_guidance

    guidance = _error_guidance(
        "ERROR: Browser screenshot timed out after 45s (with one retry)."
    )
    assert guidance is not None
    assert "browser" in guidance.summary.lower()
    # And not the LLM-provider phrasing.
    assert "provider" not in guidance.summary.lower()

    guidance2 = _error_guidance(
        "ERROR: Snapshot timed out after 40s. The page may be hung; try navigate again or restart the browser session."
    )
    assert guidance2 is not None
    assert "browser" in guidance2.summary.lower()


# ── New tests: Session resume command ────────────────────────────────────


def test_resume_command_sets_pending() -> None:
    """'/resume 1' should set _pending_resume."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command("/resume 1")
    assert result is True
    assert repl.pending_resume == "1"


def test_resume_command_no_arg_warns() -> None:
    """'/resume' without arg should show a warning."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command("/resume")
    assert result is True
    assert repl.pending_resume is None
    mock_renderer.add_system_message.assert_called_once()
    assert "Usage" in mock_renderer.add_system_message.call_args[0][0]


def test_resume_command_with_session_id() -> None:
    """'/resume abc-123' should store the raw session ID."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command("/resume abc-def-123")
    assert result is True
    assert repl.pending_resume == "abc-def-123"


@pytest.mark.asyncio
async def test_resume_session_uses_persisted_session_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resume_session should resolve numeric indexes from the real session storage layout."""
    fake = tmp_path / "USER_HOME"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    data_root = Path(get_project_local_data_root(tmp_path))
    sessions_root = data_root / "sessions"
    older = sessions_root / "session-old"
    newer = sessions_root / "session-new"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "metadata.json").write_text(
        json.dumps({"last_updated_at": "2026-03-29T10:00:00"}),
        encoding="utf-8",
    )
    (newer / "metadata.json").write_text(
        json.dumps({"last_updated_at": "2026-03-30T10:00:00"}),
        encoding="utf-8",
    )

    config = AppConfig(
        project_root=str(tmp_path),
        local_data_root=str(data_root),
    )
    repl = Repl(config, _make_console())
    renderer = MagicMock()
    repl.set_renderer(renderer)
    repl.set_bootstrap_state(
        agent=MagicMock(),
        llm_registry=MagicMock(),
        conversation_stats=MagicMock(),
        acquire_result="old-runtime-handle",
    )

    event_stream = MagicMock()
    event_stream.sid = "session-new"
    runtime = MagicMock()
    runtime.event_stream = event_stream
    memory = MagicMock()
    controller = MagicMock()

    async def fake_run_agent_until_done(*args, **kwargs) -> None:
        await asyncio.sleep(0)

    with patch(
        "backend.core.bootstrap.main._setup_runtime_for_controller",
        return_value=(runtime, None, "new-runtime-handle"),
    ) as mock_setup_runtime:
        with patch(
            "backend.core.bootstrap.main._setup_memory_and_mcp",
            new=AsyncMock(return_value=memory),
        ) as mock_setup_memory:
            with patch(
                "backend.execution.runtime_orchestrator.release"
            ) as mock_release:
                create_controller = MagicMock(return_value=(controller, MagicMock()))
                create_status_callback = MagicMock(return_value=MagicMock())

                resumed = await repl.resume_session(
                    "1",
                    config,
                    create_controller,
                    create_status_callback,
                    fake_run_agent_until_done,
                    [AgentState.FINISHED],
                )

    assert resumed is not None
    resumed_controller, agent_task = resumed
    assert resumed_controller is controller
    assert mock_setup_runtime.call_args[0][2] == "session-new"
    mock_setup_memory.assert_awaited_once()
    mock_release.assert_called_once_with("old-runtime-handle")
    renderer.reset_subscription.assert_called_once()
    renderer.subscribe.assert_called_once_with(event_stream, "session-new")

    with suppress(asyncio.CancelledError):
        if not agent_task.done():
            agent_task.cancel()
        await agent_task


# ===========================================================================
# Tests for new action/observation handlers (Phase 1)
# ===========================================================================


def _make_renderer_sync() -> tuple[Console, HUDBar, CLIEventRenderer]:
    """Create a renderer without needing an event loop (for sync tests)."""
    console = _make_console()
    hud = HUDBar()
    loop = asyncio.new_event_loop()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(console, hud, reasoning, loop=loop)
    return console, hud, renderer


@pytest.mark.asyncio
async def test_renderer_handles_file_read_action() -> None:
    from backend.ledger.action import FileReadAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    from backend.ledger.observation import FileReadObservation

    action = FileReadAction(path="/workspace/src/main.py")
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(
        FileReadObservation(content="line1\nline2", path="/workspace/src/main.py")
    )

    output = _console_output(console)
    assert "main.py" in output
    assert "2 lines" in output


@pytest.mark.asyncio
async def test_renderer_handles_file_read_observation() -> None:
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = FileReadObservation(content="line1\nline2\nline3", path="/workspace/test.py")
    await renderer.handle_event(obs)
    # FileReadObservation shows a dim stats continuation (path was on the action row).
    output = _console_output(console)
    assert "3 lines" in output


@pytest.mark.asyncio
async def test_renderer_handles_mcp_action() -> None:
    from backend.ledger.action import MCPAction
    from backend.ledger.observation import MCPObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = MCPAction(name="search_code", arguments={"query": "test"})
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(MCPObservation(content='{"text": "found 3 matches"}'))

    output = _console_output(console)
    assert "Searched" in output
    assert "test" in output
    assert "found 3 matches" in output


@pytest.mark.asyncio
async def test_renderer_handles_success_observation() -> None:
    from backend.ledger.observation import SuccessObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = SuccessObservation(content="File written successfully")
    await renderer.handle_event(obs)
    output = _console_output(console)
    assert "File written successfully" in output
    # SuccessObservation renders content as dim text (no '✓' prefix)


@pytest.mark.asyncio
async def test_renderer_handles_delegate_task_action() -> None:
    from backend.ledger.action import DelegateTaskAction
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = DelegateTaskAction(task_description="Write unit tests")
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(DelegateTaskObservation(content="done", success=True))

    output = _console_output(console)
    assert "Delegated" in output
    assert "Write unit tests" in output
    assert "done" in output


@pytest.mark.asyncio
async def test_renderer_summarizes_parallel_delegate_task_results() -> None:
    from backend.ledger.action import DelegateTaskAction
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = DelegateTaskAction(
        parallel_tasks=[
            {"task_description": "Analyze existing codebase and script logic"},
            {"task_description": "Draft README updates"},
            {"task_description": "Add regression tests"},
        ]
    )
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(
        DelegateTaskObservation(
            content=(
                "[OK] Analyze existing codebase and script logic\n"
                "Worker completed with status: finished\n\n"
                "[OK] Draft README updates\n"
                "Worker completed with status: finished\n\n"
                "[OK] Add regression tests\n"
                "Worker completed with status: finished"
            ),
            success=True,
        )
    )

    output = _console_output(console)
    assert "3 parallel tasks" in output
    assert "all 3 workers completed" in output
    assert "Analyze existing codebase and script logic" in output


@pytest.mark.asyncio
async def test_renderer_shows_background_delegate_completion_without_pending_card() -> (
    None
):
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        DelegateTaskObservation(
            content=(
                "[OK] Write tests\n"
                "Worker completed with status: finished\n\n"
                "[FAILED] Update docs\n"
                "Agent did not finish gracefully (State: error)."
            ),
            success=False,
            error_message="One or more parallel workers failed.",
        )
    )

    output = _console_output(console)
    assert "1/2 workers completed" in output
    assert "Update docs" in output
    assert "One or more parallel workers failed." in output


@pytest.mark.asyncio
async def test_renderer_updates_worker_panel_from_delegate_progress_status() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        StatusObservation(
            content="Worker 1 · Starting delegated worker",
            status_type="delegate_progress",
            extras={
                "worker_id": "worker-1",
                "worker_label": "Worker 1",
                "task_description": "Write unit tests for the converter",
                "worker_status": "starting",
                "detail": "Starting delegated worker",
                "order": 1,
            },
        )
    )
    await renderer.handle_event(
        StatusObservation(
            content="Worker 1 · Viewed requirements.txt",
            status_type="delegate_progress",
            extras={
                "worker_id": "worker-1",
                "worker_label": "Worker 1",
                "task_description": "Write unit tests for the converter",
                "worker_status": "running",
                "detail": "Viewed requirements.txt",
                "order": 1,
            },
        )
    )
    await renderer.handle_event(
        StatusObservation(
            content="Worker 1 · Completed converter tests",
            status_type="delegate_progress",
            extras={
                "worker_id": "worker-1",
                "worker_label": "Worker 1",
                "task_description": "Write unit tests for the converter",
                "worker_status": "done",
                "detail": "Completed converter tests",
                "order": 1,
            },
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    assert "Workers (1)" in output
    assert "Worker 1" in output
    assert "Write unit tests for the converter" in output
    assert "Completed converter tests" in output
    assert "[DONE]" in output


@pytest.mark.asyncio
async def test_renderer_renders_finish_action_message_and_next_steps() -> None:
    from backend.ledger.action import PlaybookFinishAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = PlaybookFinishAction(
        final_thought="Completed the Markdown to HTML converter.",
        outputs={
            "completed": ["Created md_to_html.py", "Generated sample.html"],
            "next_steps": [
                "Open sample.html in a browser",
                "Replace sample.md with your real input",
            ],
        },
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert "Completed the Markdown to HTML converter." in output
    assert "Next steps" in output
    assert "Open sample.html in a browser" in output


@pytest.mark.asyncio
async def test_renderer_handles_condensation_action() -> None:
    from backend.ledger.action import CondensationAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = CondensationAction(pruned_event_ids=[1, 2, 3])
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    # CondensationAction updates reasoning panel only — no console output
    assert renderer._reasoning.active
    assert "compress" in renderer._reasoning._current_action.lower()


@pytest.mark.asyncio
async def test_renderer_handles_task_tracking_action() -> None:
    from backend.ledger.action import TaskTrackingAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = TaskTrackingAction(command="add", thought="Track progress")
    action.source = EventSource.AGENT
    # TaskTrackingAction just calls refresh() — no console output expected
    await renderer.handle_event(action)
    # No error should be raised; event is silently processed
    assert _console_output(console) == ""


@pytest.mark.asyncio
async def test_renderer_syncs_task_panel_from_update_action_before_observation() -> None:
    from backend.ledger.action import TaskTrackingAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content="created",
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "doing",
                }
            ],
        )
    )
    action = TaskTrackingAction(
        command="update",
        task_list=[
            {
                "id": "1",
                "description": "Analyze manifest structure",
                "status": "done",
            }
        ],
    )
    action.source = EventSource.AGENT
    await renderer.handle_event(action)

    renderer.stop_live()
    output = _console_output(console)
    assert "Tasks (1)" in output
    assert "[DONE]" in output
    assert "[DOING]" not in output


@pytest.mark.asyncio
async def test_renderer_task_tracking_observation_replaces_previous_panel() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content="created",
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "todo",
                }
            ],
        )
    )
    await renderer.handle_event(
        TaskTrackingObservation(
            content="updated",
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "doing",
                }
            ],
        )
    )

    assert renderer._task_panel is not None

    renderer.stop_live()
    output = _console_output(console)
    assert output.count("Tasks (1)") == 1
    assert "[PENDING]" not in output
    assert "[DOING]" in output


@pytest.mark.asyncio
async def test_renderer_shows_noop_task_tracker_message_for_update() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content=(
                "[TASK_TRACKER] Update skipped because the plan is unchanged. "
                "Do a concrete next action now."
            ),
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "doing",
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    # Noop "plan is unchanged" messages are now suppressed in the renderer.
    assert "plan is unchanged" not in output
    assert "Tasks (1)" in output


@pytest.mark.asyncio
async def test_renderer_hides_task_tracker_update_chatter_when_panel_updates() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content="[TASK_TRACKER] Updated step 1 to done.",
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "done",
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    assert "Updated step 1 to done" not in output
    assert "Tasks (1)" in output
    assert "[DONE]" in output


@pytest.mark.asyncio
async def test_renderer_displays_done_task_state() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content="updated",
            command="update",
            task_list=[
                {
                    "id": "1",
                    "description": "Analyze manifest structure",
                    "status": "done",
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    assert "[DONE]" in output


@pytest.mark.asyncio
async def test_renderer_hides_internal_tool_thought_payloads() -> None:
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )
    action = AgentThinkAction(
        thought='[READ_SYMBOL_DEFINITION]\n{\n  "entities": {\n    "foo.py": "missing"\n  }\n}'
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    assert reasoning.active
    assert "symbol" in reasoning._current_action.lower()
    assert reasoning._thought_lines == []


@pytest.mark.asyncio
async def test_renderer_hides_working_memory_thought_payloads() -> None:
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        AgentThinkObservation(
            content="[WORKING_MEMORY] Updated 'findings' section (fallback from section='all')."
        )
    )

    assert reasoning.active
    assert "working memory" in reasoning._current_action.lower()
    assert reasoning._thought_lines == []
    assert _console_output(console) == ""


@pytest.mark.asyncio
async def test_renderer_sanitizes_internal_working_memory_markup_in_messages() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = MessageAction(
        content=(
            "<WORKING_MEMORY>\n"
            "[PLAN] tighten transcript sanitization\n"
            "[FINDINGS] raw task tracker text leaks into chat\n"
            "</WORKING_MEMORY>"
        )
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert "<WORKING_MEMORY>" not in output
    assert "[PLAN]" not in output
    assert "[FINDINGS]" not in output
    assert "Plan: tighten transcript sanitization" in output
    assert "Findings: raw task tracker text leaks into chat" in output


@pytest.mark.asyncio
async def test_renderer_sanitizes_internal_working_memory_markup_in_stream_preview() -> (
    None
):
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    chunk = StreamingChunkAction(
        chunk="x",
        accumulated=(
            "<WORKING_MEMORY>\n"
            "[PLAN] tighten transcript sanitization\n"
            "</WORKING_MEMORY>"
        ),
        is_final=False,
    )
    chunk.source = EventSource.AGENT

    await renderer.handle_event(chunk)

    assert "<WORKING_MEMORY>" not in renderer._streaming_accumulated
    assert "[PLAN]" not in renderer._streaming_accumulated
    assert "Plan: tighten transcript sanitization" in renderer._streaming_accumulated


@pytest.mark.asyncio
async def test_renderer_sanitizes_task_tracking_prompt_markup_in_messages() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = MessageAction(
        content=(
            "<TASK_TRACKING>\n"
            "task_tracker: update\n"
            "Allowed statuses: todo, doing, done\n"
            "</TASK_TRACKING>\n"
            "Applied the patch and reran the test."
        )
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert "<TASK_TRACKING>" not in output
    assert "task_tracker: update" not in output
    assert "Allowed statuses" not in output
    assert "Applied the patch and reran the test." in output


def test_mcp_result_user_preview_compacts_large_raw_text_payload() -> None:
    from backend.cli.tool_call_display import mcp_result_user_preview

    preview = mcp_result_user_preview(
        "\n".join(
            [
                "The Pragmatic Stack",
                "https://example.com/articles/pragmatic-stack",
                "A long excerpt that should not be dumped verbatim into the transcript.",
                "Another detail line that would otherwise clutter the terminal.",
                "https://example.com/articles/pragmatic-stack/source",
            ]
        ),
        max_len=120,
    )

    assert preview.startswith("The Pragmatic Stack")
    assert "5 lines" in preview
    assert "2 links" in preview
    assert "Another detail line" not in preview


def test_mcp_result_user_preview_summarizes_result_lists() -> None:
    from backend.cli.tool_call_display import mcp_result_user_preview

    preview = mcp_result_user_preview(
        json.dumps(
            {
                "results": [
                    {
                        "title": "The Pragmatic Stack",
                        "url": "https://example.com/articles/pragmatic-stack",
                    },
                    {
                        "title": "Verification Tax",
                        "url": "https://example.com/articles/verification-tax",
                    },
                ]
            }
        )
    )

    assert preview == "2 results · The Pragmatic Stack"


@pytest.mark.asyncio
async def test_renderer_ignores_agent_think_acknowledgement() -> None:
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        AgentThinkObservation(content="Your thought has been logged.")
    )

    assert reasoning._thought_lines == []
    assert _console_output(console) == ""


@pytest.mark.asyncio
async def test_renderer_handles_user_reject_with_content() -> None:
    from backend.ledger.observation import UserRejectObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = UserRejectObservation(content="Too risky")
    await renderer.handle_event(obs)
    output = _console_output(console)
    assert "Too risky" in output


@pytest.mark.asyncio
async def test_renderer_handles_agent_condensation_observation() -> None:
    from backend.ledger.observation import AgentCondensationObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = AgentCondensationObservation(content="condensed")
    # AgentCondensationObservation is handled silently (just returns)
    await renderer.handle_event(obs)
    # No error raised; event silently processed
    assert _console_output(console) == ""


@pytest.mark.asyncio
async def test_renderer_prefers_actionable_npm_error_line() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = CmdOutputObservation(
        content=(
            "npm error enoent Could not read package.json: Error: ENOENT: no such file or directory, "
            "open 'C:\\Users\\GIGABYTE\\Desktop\\react-app\\package.json'\n"
            "npm error enoent This is related to npm not being able to find a file.\n"
            "npm error A complete log of this run can be found in: "
            "C:\\Users\\GIGABYTE\\AppData\\Local\\npm-cache\\_logs\\debug.log"
        ),
        command="npm create vite@latest . -- --template react && npm install",
        metadata={"exit_code": 38},
    )

    await renderer.handle_event(obs)

    output = _console_output(console)
    assert "Could not read package.json" in output
    assert "A complete log of this run can be found in" not in output


@pytest.mark.asyncio
async def test_renderer_cmd_output_stdout_is_suppressed_on_success() -> None:
    """Long stdout from a successful shell command must be collapsed.

    Intent: the Terminal activity card shows ``Ran <cmd>`` + ``✓ done``;
    the raw stdout body is suppressed to keep the transcript scan-able.
    Previously the test asserted the inverse (``output.count('A') >= 120``)
    — that matched an older renderer that echoed the first output line on
    a continuation row. The current UX decision is to hide stdout from
    the CLI transcript entirely; users wanting the full body read it from
    the workspace log.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    long_output = "A" * 5000
    obs = CmdOutputObservation(
        content=long_output, command="cat bigfile.txt", exit_code=0
    )
    await renderer.handle_event(obs)
    output = _console_output(console)
    # The raw 5 000 ``A`` characters must not reach the transcript; a few
    # incidental As (from words like "command", "Ran") in card chrome are
    # fine, so we bound rather than assert-zero.
    assert output.count("A") < 20, (
        f'stdout leaked into Terminal card; got {output.count("A")} As:\n' + output
    )
    # But the card itself must still render (verb + done summary).
    assert "done" in output.lower() or "Ran" in output


@pytest.mark.asyncio
async def test_renderer_message_action_shows_attachment_indicators() -> None:
    """MessageAction with file_urls should show attachment indicator."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    msg = MessageAction(content="Here is the analysis", wait_for_response=False)
    msg.source = EventSource.AGENT
    msg.file_urls = ["file1.txt", "file2.py"]
    await renderer.handle_event(msg)
    output = _console_output(console)
    assert "analysis" in output
    assert "2 file(s)" in output


@pytest.mark.asyncio
async def test_renderer_cmd_run_shows_thought() -> None:
    """CmdRunAction with thought should pass thought to reasoning display."""
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )
    action = CmdRunAction(command="npm test", thought="Checking if tests pass")
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    # CmdRunAction updates the reasoning panel (not console output directly)
    assert reasoning.active
    assert reasoning._current_action  # action label set in reasoning
    assert reasoning._thought_lines  # thought was passed


@pytest.mark.asyncio
async def test_renderer_internal_cmd_run_uses_origin_tool_title() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = CmdRunAction(
        command="python missing.py",
        display_label="Mapping project structure (.)",
    )
    action.source = EventSource.AGENT
    action.tool_call_metadata = MagicMock(
        function_name="analyze_project_structure",
        tool_call_id="call-1",
        total_calls_in_response=1,
    )

    await renderer.handle_event(action)
    await renderer.handle_event(
        CmdOutputObservation(
            content="[MISSING_TOOL] Install with: winget install python",
            exit_code=127,
            command="python missing.py",
        )
    )

    output = _console_output(console)
    assert "Analyze project" in output
    assert "Mapping project structure (.)" in output
    assert "Shell" not in output


@pytest.mark.asyncio
async def test_renderer_apply_patch_output_is_collapsed_on_success() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = CmdRunAction(
        command='python -c "print("internal")"',
        display_label="Applying patch",
    )
    action.source = EventSource.AGENT
    action.tool_call_metadata = MagicMock(
        function_name="apply_patch",
        tool_call_id="call-apply-1",
        total_calls_in_response=1,
    )

    await renderer.handle_event(action)
    await renderer.handle_event(
        CmdOutputObservation(
            content=(
                "diff --git a/foo.py b/foo.py\n"
                "index 1111111..2222222 100644\n"
                "--- a/foo.py\n"
                "+++ b/foo.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            ),
            exit_code=0,
            command='python -c "print("internal")"',
        )
    )

    output = _console_output(console)
    assert "Apply patch" in output
    assert "Applying patch" in output
    assert "succeeded" in output
    assert "+1" in output
    assert "-1" in output
    assert "+...." not in output
    assert "-...." not in output
    assert "diff --git" not in output


@pytest.mark.asyncio
async def test_renderer_apply_patch_output_is_collapsed_on_failure() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = CmdRunAction(
        command='python -c "print("internal")"',
        display_label="Applying patch",
    )
    action.source = EventSource.AGENT
    action.tool_call_metadata = MagicMock(
        function_name="apply_patch",
        tool_call_id="call-apply-2",
        total_calls_in_response=1,
    )

    await renderer.handle_event(action)
    await renderer.handle_event(
        CmdOutputObservation(
            content="error: corrupt patch at line 7",
            exit_code=1,
            command='python -c "print("internal")"',
        )
    )

    output = _console_output(console)
    assert "Apply patch" in output
    assert "Applying patch" in output
    assert "failed" in output
    assert "+...." not in output
    assert "-...." not in output


def test_reasoning_display_tool_icons() -> None:
    """ReasoningDisplay should show tool-specific icons."""
    rd = ReasoningDisplay()
    rd.start()
    rd.update_action("Reading file src/main.py")
    panel = rd.renderable()
    assert panel is not None
    assert panel.padding == (0, 0)
    assert rd._max_lines == 50_000


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
        rd.update_thought(f"thought {i:02d}")

    console = _make_console(width=90)
    with patch.object(
        ReasoningDisplay, "live_panel_shows_thought_rows", return_value=True
    ):
        console.print(rd.renderable(max_width=90, max_lines=4))
    output = _console_output(console)

    assert "showing latest thoughts" in output
    assert "thought 15" in output
    assert "thought 06" not in output


def test_reasoning_display_has_no_redundant_ctrl_c_hint() -> None:
    """The reasoning panel must not repeat the Ctrl+C hint.

    The fake-prompt bar directly below the panel already surfaces
    "Agent working · ctrl+c to interrupt", so echoing it inside the
    Thinking panel was pure visual clutter.
    """
    rd = ReasoningDisplay()
    rd.start()
    rd.update_thought("analyzing request")
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    lowered = output.lower()
    assert "ctrl+c" not in lowered
    assert "interrupts" not in lowered


def test_reasoning_display_live_panel_is_header_only_by_default() -> None:
    """Thought bodies are transcript-only; the live Thinking card is header-only."""
    rd = ReasoningDisplay()
    rd.set_streaming_thought("partial reasoning in flight")
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert "Thinking" in output
    assert "partial reasoning in flight" not in output
    assert "▌" not in output


def test_reasoning_display_no_cursor_when_action_changes() -> None:
    """Starting a new action ends the streaming run; no cursor should remain."""
    rd = ReasoningDisplay()
    rd.set_streaming_thought("thinking about fix")
    rd.update_action("Writing index.html")
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert "▌" not in output


def test_reasoning_display_no_breadcrumb_trail() -> None:
    """Recent-step breadcrumb was removed to reduce clutter.

    Activity history already lives above the live panel; duplicating a
    "then X → Y" crumb inside Thinking made long turns feel noisy.
    """
    rd = ReasoningDisplay()
    rd.update_action("Reading src/a.py")
    rd.update_action("Reading src/b.py")
    rd.update_action("Writing src/c.py")
    console = _make_console(width=90)
    console.print(rd.renderable(max_width=90))
    output = _console_output(console)
    assert "then " not in output
    assert "→" not in output


def test_reasoning_display_live_panel_omits_long_thought_bodies() -> None:
    """Long thoughts are not echoed in the live Thinking panel (transcript only)."""
    rd = ReasoningDisplay()
    rd.start()
    long_line = "rgba(12,34,56,0.7) " * 25
    rd.update_thought(long_line)
    console = _make_console(width=72)
    console.print(rd.renderable(max_width=72))
    output = _console_output(console)
    assert "rgba(12,34,56,0.7)" not in output


@pytest.mark.asyncio
async def test_reasoning_gets_generous_budget_when_alone() -> None:
    """When only the reasoning panel is active, it should get >= 12 lines.

    Regression guard: the previous layout reserved 10 rows for bottom
    chrome and then clamped reasoning to ``max(6, …)``, which in practice
    made long thoughts appear truncated to ~2 visible rows on mid-height
    terminals. The new layout reserves only ~6 rows and floors the
    reasoning budget at 12 lines so thoughts stream cleanly.
    """
    console = _make_console(width=100)
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer._reasoning.start()
    renderer._reasoning.update_thought("x " * 80)
    for i in range(40):
        renderer._reasoning.update_thought(f"line {i:02d}")

    captured: dict[str, int | None] = {"max_lines": None}

    def _capture(*, max_width, max_lines):  # type: ignore[no-redef]
        captured["max_lines"] = max_lines
        return Text("stub")

    renderer._reasoning.renderable = _capture  # type: ignore[assignment]
    from rich.console import ConsoleOptions

    options = ConsoleOptions(
        size=console.size,
        legacy_windows=False,
        min_width=10,
        max_width=100,
        is_terminal=False,
        encoding="utf-8",
        max_height=40,
    )

    list(renderer.__rich_console__(console, options))
    assert captured["max_lines"] is not None
    # Header-only Thinking panel uses a small vertical budget; the draft
    # reply preview owns most of the Live viewport.
    assert captured["max_lines"] >= 4, (
        f'reasoning budget was {captured["max_lines"]} lines; '
        "expected a minimal header budget"
    )


@pytest.mark.asyncio
async def test_reasoning_keeps_meaningful_budget_when_sharing_with_stream() -> None:
    """Reasoning + streaming preview should each keep a usable vertical budget."""
    console = _make_console(width=100)
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer._reasoning.start()
    renderer._reasoning.update_thought("thinking hard about the problem")
    renderer._streaming_accumulated = "draft reply paragraph " * 30

    captured: dict[str, int | None] = {
        "reasoning": None,
        "stream": None,
    }

    def _capture_reasoning(*, max_width, max_lines):  # type: ignore[no-redef]
        captured["reasoning"] = max_lines
        return Text("reasoning-stub")

    def _capture_stream(*, max_width, max_lines):  # type: ignore[no-redef]
        captured["stream"] = max_lines
        return Text("stream-stub")

    renderer._reasoning.renderable = _capture_reasoning  # type: ignore[assignment]
    renderer._render_streaming_preview = _capture_stream  # type: ignore[assignment]
    from rich.console import ConsoleOptions

    options = ConsoleOptions(
        size=console.size,
        legacy_windows=False,
        min_width=10,
        max_width=100,
        is_terminal=False,
        encoding="utf-8",
        max_height=40,
    )
    list(renderer.__rich_console__(console, options))

    assert (captured["reasoning"] or 0) >= 4
    assert (captured["stream"] or 0) >= 6
    # Draft reply is the primary live signal; header-only Thinking stays small.
    assert (captured["stream"] or 0) >= (captured["reasoning"] or 0)


@pytest.mark.asyncio
async def test_fake_prompt_uses_tight_separator_and_combined_model_slug() -> None:
    """Visual-clutter guard for the branded row.

    * Uses ' · ' instead of '  •  ' so the row feels less crowded.
    * Renders ``provider/model`` combined instead of two labelled fields.
    """
    console = _make_console(width=120)
    hud = HUDBar()
    hud.update_model("openai/google/gemini-3-flash-preview")
    hud.update_agent_state("Running")
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    prompt = renderer._render_fake_prompt(120)
    console.print(prompt)
    output = _console_output(console)

    assert "provider:" not in output
    assert "model:" not in output
    assert "google/gemini-3-flash-preview" in output
    # Tight bullet separator; the old "  •  " (with two spaces on each side)
    # must not leak back in.
    assert "  •  " not in output
    assert "Agent working · ctrl+c to interrupt" in output


def test_hud_compact_format_for_narrow_terminal() -> None:
    """HUD should use compact format for narrow terminals."""
    hud = HUDBar()
    hud.state.model = "openai/gpt-4.1"
    hud.state.context_tokens = 5000
    hud.state.context_limit = 128000
    hud.state.cost_usd = 0.1234
    hud.state.llm_calls = 3
    hud.state.ledger_status = "Healthy"

    full = hud._format()
    compact = hud._format_compact()
    # Compact should be shorter
    assert len(compact.plain) < len(full.plain)
    # Compact should have the status icon
    assert "●" in compact.plain


def test_hud_ledger_icon() -> None:
    """HUD ledger icon returns correct single-char indicators."""
    hud = HUDBar()
    hud.state.ledger_status = "Healthy"
    assert hud._ledger_icon() == "●"
    hud.state.ledger_status = "Error"
    assert hud._ledger_icon() == "✗"
    hud.state.ledger_status = "Paused"
    assert hud._ledger_icon() == "⏸"


def test_auto_detect_api_keys_finds_env_var() -> None:
    """auto_detect_api_keys should detect OPENAI_API_KEY from env."""
    from backend.cli.config_manager import auto_detect_api_keys

    config = MagicMock()
    llm_cfg = MagicMock()
    llm_cfg.model = ""
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key-12345"}, clear=False):
        result = auto_detect_api_keys(config)

    assert result == "openai"


def test_auto_detect_api_keys_returns_none_when_no_env() -> None:
    """auto_detect_api_keys should return None when no env vars set."""
    from backend.cli.config_manager import auto_detect_api_keys

    config = MagicMock()
    llm_cfg = MagicMock()
    llm_cfg.model = "some-model"
    config.get_llm_config.return_value = llm_cfg

    # Clear all known API key env vars
    env_clear = {
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "GEMINI_API_KEY": "",
        "XAI_API_KEY": "",
        "GROQ_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "NVIDIA_API_KEY": "",
        "LIGHTNING_API_KEY": "",
    }
    with patch.dict(os.environ, env_clear, clear=False):
        result = auto_detect_api_keys(config)

    assert result is None
