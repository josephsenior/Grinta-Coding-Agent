"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from backend.core.enums import AgentState, EventSource
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
    MessageAction,
    NullAction,
    RecallAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    AgentThinkObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileWriteObservation,
    NullObservation,
    Observation,
    RecallObservation,
    StatusObservation,
    UserRejectObservation,
)

from backend.cli.hud import HUDBar

if TYPE_CHECKING:
    from backend.cli.reasoning_display import ReasoningDisplay
    from backend.ledger.stream import EventStream

# Events to silently skip (mirrors gateway filtering).
_SKIP_ACTIONS = (NullAction,)
_SKIP_OBSERVATIONS = (NullObservation,)
_IDLE_STATES = {
    AgentState.AWAITING_USER_INPUT,
    AgentState.FINISHED,
    AgentState.ERROR,
    AgentState.STOPPED,
    AgentState.PAUSED,
    AgentState.REJECTED,
}

# Subscriber ID for the CLI renderer.
_SUBSCRIBER = EventStreamSubscriber.CLI


class CLIEventRenderer:
    """Bridges EventStream → live rich layout."""

    def __init__(
        self,
        console: Console,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        max_budget: float | None = None,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._loop = loop or asyncio.get_event_loop()
        self._history: deque[Any] = deque(maxlen=96)
        self._live: Live | None = None
        self._streaming_accumulated = ''
        self._streaming_final = False
        self._current_state: AgentState | None = None
        self._state_event = asyncio.Event()
        self._body_title = 'Grinta'
        self._subscribed = False
        self._max_budget = max_budget
        self._budget_warned_80 = False
        self._budget_warned_100 = False
        # Per-turn metric snapshots (used to compute deltas at turn completion)
        self._turn_start_cost: float = 0.0
        self._turn_start_tokens: int = 0
        self._turn_start_calls: int = 0

    @property
    def current_state(self) -> AgentState | None:
        return self._current_state

    @property
    def history(self) -> tuple[Any, ...]:
        return tuple(self._history)

    @property
    def streaming_preview(self) -> str:
        return self._streaming_accumulated

    @property
    def budget_warned_80(self) -> bool:
        return self._budget_warned_80

    @property
    def budget_warned_100(self) -> bool:
        return self._budget_warned_100

    def attach_live(self, live: Live) -> None:
        self._live = live
        self.refresh()

    async def handle_event(self, event: Any) -> None:
        await self._on_event(event)

    def reset_subscription(self) -> None:
        self._subscribed = False

    @contextmanager
    def suspend_live(self):
        live = self._live
        if live is None:
            yield
            return

        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed during suspend', exc_info=True)

        try:
            yield
        finally:
            try:
                live.start()
            except Exception:
                logger.debug('Live.start() failed during resume', exc_info=True)
            self.refresh()

    def refresh(self) -> None:
        if self._live is not None:
            self._live.update(self, refresh=True)

    def begin_turn(self) -> None:
        self._current_state = AgentState.RUNNING
        self._hud.update_ledger('Healthy')
        self._state_event.clear()
        # Snapshot metrics so we can compute per-turn deltas at completion.
        self._turn_start_cost = self._hud.state.cost_usd
        self._turn_start_tokens = self._hud.state.context_tokens
        self._turn_start_calls = self._hud.state.llm_calls
        self.refresh()

    async def wait_for_state_change(
        self, wait_timeout_sec: float = 0.25
    ) -> AgentState | None:
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except asyncio.TimeoutError:
            return self._current_state
        self._state_event.clear()
        return self._current_state

    def clear_history(self) -> None:
        self._history.clear()
        self._clear_streaming_preview()
        self._reasoning.stop()
        self.refresh()

    def add_user_message(self, text: str) -> None:
        self._append_history(
            Panel(
                Markdown(text),
                title='[bold cyan]You[/bold cyan]',
                border_style='cyan',
                padding=(0, 1),
            )
        )

    def add_system_message(self, text: str, *, title: str = 'Info') -> None:
        self._append_history(
            Panel(
                Text(text, style='dim'),
                title=title,
                border_style='bright_black',
                padding=(0, 1),
            )
        )

    def add_markdown_block(self, title: str, text: str) -> None:
        self._append_history(
            Panel(
                Markdown(text),
                title=title,
                border_style='bright_black',
                padding=(0, 1),
            )
        )

    # -- subscription ------------------------------------------------------

    def subscribe(self, event_stream: EventStream, sid: str) -> None:
        if self._subscribed:
            return
        event_stream.subscribe(_SUBSCRIBER, self._on_event_threadsafe, sid)
        self._subscribed = True

    def _on_event_threadsafe(self, event: Any) -> None:
        """Called from the EventStream's background thread."""
        self._loop.call_soon_threadsafe(asyncio.ensure_future, self._on_event(event))

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        body_items = list(self._history)[-12:]
        if self._streaming_accumulated:
            body_items.append(self._render_streaming_preview())
        if self._reasoning.active:
            body_items.append(self._reasoning.renderable())
        if not body_items:
            body_items.append(Text('Ready for input.', style='dim'))

        layout = Layout()
        layout.split_column(
            Layout(
                Panel(
                    Group(*body_items),
                    title=self._body_title,
                    border_style='bright_black',
                    padding=(0, 1),
                ),
                ratio=1,
                name='body',
            ),
            Layout(self._hud, size=1, name='footer'),
        )
        yield layout

    # -- main dispatch -----------------------------------------------------

    async def _on_event(self, event: Any) -> None:
        # --- filter -------------------------------------------------------
        if isinstance(event, _SKIP_ACTIONS) or isinstance(event, _SKIP_OBSERVATIONS):
            return

        self._update_metrics(event)

        source = getattr(event, 'source', None)

        # --- actions from AGENT -------------------------------------------
        if isinstance(event, Action) and source == EventSource.AGENT:
            self._handle_agent_action(event)
            return

        # --- observations -------------------------------------------------
        if isinstance(event, Observation):
            self._handle_observation(event)
            return

        self.refresh()

    # -- action handlers ---------------------------------------------------

    def _handle_agent_action(self, action: Action) -> None:
        if isinstance(action, StreamingChunkAction):
            self._handle_streaming_chunk(action)
            return

        if isinstance(action, MessageAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            if action.content.strip():
                self._append_history(
                    Panel(
                        Markdown(action.content),
                        title='[bold magenta]Grinta[/bold magenta]',
                        border_style='magenta',
                        padding=(0, 1),
                    )
                )
            else:
                self.refresh()
            return

        if not isinstance(action, AgentThinkAction):
            self._clear_streaming_preview()

        if isinstance(action, AgentThinkAction):
            thought = getattr(action, 'thought', '') or getattr(action, 'content', '')
            if thought:
                self._ensure_reasoning()
                self._reasoning.update_thought(thought)
                self.refresh()
            return

        if isinstance(action, CmdRunAction):
            self._ensure_reasoning()
            cmd_display = action.command
            if len(cmd_display) > 120:
                cmd_display = cmd_display[:117] + '…'
            self._reasoning.update_action(f'Running: {cmd_display}')
            self.refresh()
            return

        if isinstance(action, FileEditAction):
            self._ensure_reasoning()
            self._reasoning.update_action(f'Editing: {action.path}')
            self.refresh()
            return

        if isinstance(action, FileWriteAction):
            self._ensure_reasoning()
            self._reasoning.update_action(f'Writing: {action.path}')
            self.refresh()
            return

        if isinstance(action, RecallAction):
            self._ensure_reasoning()
            query = getattr(action, 'query', '')
            label = f'Recalling: {query}' if query else 'Recalling context…'
            self._reasoning.update_action(label)
            self.refresh()
            return

        self.refresh()

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        self._streaming_accumulated = action.accumulated
        self._streaming_final = action.is_final
        self.refresh()

    # -- observation handlers ----------------------------------------------

    def _handle_observation(self, obs: Observation) -> None:
        if isinstance(obs, AgentStateChangedObservation):
            self._handle_state_change(obs)
            return

        if isinstance(obs, AgentThinkObservation):
            thought = getattr(obs, 'thought', '') or getattr(obs, 'content', '')
            if thought:
                self._ensure_reasoning()
                self._reasoning.update_thought(thought)
                self.refresh()
            return

        if isinstance(obs, CmdOutputObservation):
            self._reasoning.stop()
            exit_code = getattr(obs, 'exit_code', None)
            output = getattr(obs, 'content', '')
            header_style = 'green' if exit_code == 0 else 'red'
            header = f'exit {exit_code}' if exit_code is not None else 'output'
            truncated = len(output) > 4000
            display_output = output[:4000]
            body_parts: list[Any] = []
            if display_output:
                body_parts.append(
                    Syntax(display_output, 'text', word_wrap=True, theme='monokai')
                )
            else:
                body_parts.append(Text('(no output)', style='dim'))
            if truncated:
                body_parts.append(
                    Text(
                        f'\n⚠ Output truncated ({len(output):,} chars total, showing first 4,000)',
                        style='yellow dim',
                    )
                )
            self._append_history(
                Panel(
                    Group(*body_parts),
                    title=f'[{header_style}]{header}[/{header_style}]',
                    border_style='bright_black',
                    padding=(0, 1),
                )
            )
            return

        if isinstance(obs, (FileEditObservation, FileWriteObservation)):
            self._reasoning.stop()
            path = getattr(obs, 'path', '')
            if isinstance(obs, FileEditObservation):
                from backend.cli.diff_renderer import DiffPanel

                self._append_history(DiffPanel(obs))
            else:
                self._append_history(
                    Text(f'  ✓ {path}', style='green'),
                )
            return

        if isinstance(obs, ErrorObservation):
            self._reasoning.stop()
            error_content = getattr(obs, 'content', str(obs))
            error_lines = error_content.strip().split('\n')
            summary = error_lines[0] if error_lines else 'Unknown error'
            body = Text()
            body.append(summary + '\n', style='red bold')
            if len(error_lines) > 1:
                detail = '\n'.join(error_lines[1:])
                if len(detail) > 2000:
                    detail = detail[:2000] + '\n… (truncated)'
                body.append(detail, style='red dim')
            self._append_history(
                Panel(
                    body,
                    title='[red bold]Error[/red bold]',
                    border_style='red',
                    padding=(0, 1),
                ),
            )
            self._hud.update_ledger('Error')
            return

        if isinstance(obs, UserRejectObservation):
            self._append_history(Text('  Action rejected.', style='yellow'))
            return

        if isinstance(obs, RecallObservation):
            # Show brief recall summary — full content goes to the agent
            kb_results = getattr(obs, 'knowledge_base_results', []) or []
            recall_type = getattr(obs, 'recall_type', None)
            label = str(recall_type.value) if recall_type else 'context'
            if kb_results:
                self._append_history(
                    Text(
                        f'  📚 Recalled {label} ({len(kb_results)} knowledge results)',
                        style='dim blue',
                    )
                )
            else:
                self._append_history(Text(f'  📚 Recalled {label}', style='dim blue'))
            return

        if isinstance(obs, StatusObservation):
            content = getattr(obs, 'content', '')
            if content:
                self._append_history(Text(f'  ℹ {content}', style='dim'))
            return

        self.refresh()

    # -- state transitions -------------------------------------------------

    def _handle_state_change(self, obs: AgentStateChangedObservation) -> None:
        state = obs.agent_state
        if isinstance(state, str):
            try:
                state = AgentState(state)
            except ValueError:
                logger.debug('Ignoring unknown agent state: %s', state)
                return
        self._current_state = state
        self._state_event.set()

        # Update HUD ledger indicator on terminal states.
        if state in (AgentState.ERROR, AgentState.REJECTED):
            self._hud.update_ledger('Error')
        elif state in (AgentState.FINISHED, AgentState.STOPPED):
            self._hud.update_ledger('Idle')
        elif state == AgentState.RUNNING:
            self._hud.update_ledger('Healthy')

        if state == AgentState.AWAITING_USER_CONFIRMATION:
            self._reasoning.stop()
            self.refresh()
            return

        if state == AgentState.AWAITING_USER_INPUT:
            self._reasoning.stop()
            self.refresh()
            return

        if state == AgentState.FINISHED:
            self._reasoning.stop()
            self._clear_streaming_preview()
            stats = self._turn_stats_text()
            self._append_history(
                Text(
                    f'  ✓ Task complete. Enter a new task or /exit.{stats}', style='green dim'
                ),
            )
            return

        if state == AgentState.ERROR:
            self._reasoning.stop()
            self._clear_streaming_preview()
            stats = self._turn_stats_text()
            self._append_history(
                Text(
                    f'  ✗ Agent stopped with an error. '
                    f'Enter a follow-up message to retry, or /exit.{stats}',
                    style='red dim',
                ),
            )
            return

        if state in _IDLE_STATES:
            self._reasoning.stop()

        self.refresh()

    # -- helpers -----------------------------------------------------------

    def _turn_stats_text(self) -> str:
        """Format per-turn token/cost delta as a short summary string."""
        cost_delta = self._hud.state.cost_usd - self._turn_start_cost
        tokens_delta = self._hud.state.context_tokens - self._turn_start_tokens
        calls_delta = self._hud.state.llm_calls - self._turn_start_calls
        parts: list[str] = []
        if tokens_delta > 0:
            parts.append(HUDBar._format_tokens(tokens_delta) + ' tokens')
        if cost_delta > 0.0:
            parts.append(f'${cost_delta:.4f}')
        if calls_delta > 0:
            parts.append(f'{calls_delta} LLM call{"s" if calls_delta != 1 else ""}')
        return '  [' + ' · '.join(parts) + ']' if parts else ''

    def _ensure_reasoning(self) -> None:
        if not self._reasoning.active:
            self._reasoning.start()

    def _append_history(self, renderable: Any) -> None:
        self._history.append(renderable)
        self.refresh()

    def _clear_streaming_preview(self) -> None:
        self._streaming_accumulated = ''
        self._streaming_final = False
        self.refresh()

    def _render_streaming_preview(self) -> Panel:
        title = '[bold cyan]Streaming[/bold cyan]'
        if self._streaming_final:
            title = '[bold cyan]Streaming (finalizing)[/bold cyan]'
        return Panel(
            Markdown(self._streaming_accumulated or ''),
            title=title,
            border_style='cyan',
            padding=(0, 1),
        )

    def _update_metrics(self, event: Any) -> None:
        llm_metrics = getattr(event, 'llm_metrics', None)
        if llm_metrics is not None:
            self._hud.update_from_llm_metrics(llm_metrics)
            self._check_budget()

    def _check_budget(self) -> None:
        if not self._max_budget or self._max_budget <= 0:
            return
        cost = self._hud.state.cost_usd
        if cost >= self._max_budget and not self._budget_warned_100:
            self._budget_warned_100 = True
            self._append_history(
                Panel(
                    Text(
                        f'Budget limit reached: ${cost:.4f} / ${self._max_budget:.4f}',
                        style='red bold',
                    ),
                    title='[red bold]Budget Exceeded[/red bold]',
                    border_style='red',
                    padding=(0, 1),
                )
            )
        elif cost >= self._max_budget * 0.8 and not self._budget_warned_80:
            self._budget_warned_80 = True
            self._append_history(
                Panel(
                    Text(
                        f'Approaching budget: ${cost:.4f} / ${self._max_budget:.4f} (80%)',
                        style='yellow',
                    ),
                    title='[yellow]Budget Warning[/yellow]',
                    border_style='yellow',
                    padding=(0, 1),
                )
            )
