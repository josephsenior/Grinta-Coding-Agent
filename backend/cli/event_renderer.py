"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# Patterns for extracting / stripping <think> blocks from reasoning models.
_THINK_EXTRACT_RE = re.compile(r'<think>(.*?)(?:</think>|$)', re.DOTALL | re.IGNORECASE)
_THINK_STRIP_RE = re.compile(r'<think>.*?(?:</think>|$)', re.DOTALL | re.IGNORECASE)

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from backend.cli.hud import HUDBar
from backend.core.enums import AgentState, EventSource
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    BrowseInteractiveAction,
    ClarificationRequestAction,
    CmdRunAction,
    CondensationAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    NullAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    SignalProgressAction,
    StreamingChunkAction,
    TaskTrackingAction,
    TerminalInputAction,
    TerminalRunAction,
    UncertaintyAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    MCPObservation,
    NullObservation,
    Observation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    SignalProgressObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)

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


@dataclass(frozen=True)
class ErrorGuidance:
    """Actionable recovery copy for a rendered error."""

    summary: str
    steps: tuple[str, ...]


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return True when any pattern appears in the target text."""
    return any(pattern in text for pattern in patterns)


def _split_error_text(error_text: str) -> tuple[str, str]:
    """Split error text into a short summary line and optional detail block."""
    stripped = error_text.strip()
    if not stripped:
        return 'Unknown error', ''
    lines = stripped.splitlines()
    summary = lines[0].strip() or 'Unknown error'
    detail = '\n'.join(line.rstrip() for line in lines[1:]).strip()
    if len(detail) > 2000:
        detail = detail[:2000] + '\n... (truncated)'
    return summary, detail


def _error_guidance(error_text: str) -> ErrorGuidance | None:
    """Return actionable recovery steps for common CLI error patterns."""
    lower = error_text.lower()
    if 'no api key or model configured' in lower or (
        'initialization failed' in lower
        and _contains_any(
            lower,
            (
                'authenticationerror',
                'invalid api key',
                'api_key',
                'unauthorized',
                '401',
            ),
        )
    ):
        return ErrorGuidance(
            summary='The engine could not finish startup with the current credentials.',
            steps=(
                'Restart grinta and complete onboarding so it can prompt for a model and API key.',
                'Or update settings.json with a valid provider, model, and API key before retrying.',
                'Rerun the same task after saving the new settings.',
            ),
        )
    if _contains_any(
        lower,
        (
            'resume failed',
            'no event stream',
            'session bootstrap state is incomplete',
        ),
    ):
        return ErrorGuidance(
            summary='This saved session could not be reopened cleanly.',
            steps=(
                'Run /sessions and try a different session if the current one is stale or incomplete.',
                'If the session files were removed, start a new task in the current project.',
            ),
        )
    if _contains_any(lower, ('timeout', 'timed out')):
        return ErrorGuidance(
            summary='The provider did not answer before the CLI gave up waiting.',
            steps=(
                'Check your network connection and the provider status page.',
                'Retry with a shorter request or switch to a faster model in /settings.',
            ),
        )
    if _contains_any(
        lower,
        (
            '401',
            'unauthorized',
            'invalid api key',
            'authenticationerror',
            'api key rejected',
        ),
    ):
        return ErrorGuidance(
            summary='The provider rejected the configured credentials.',
            steps=(
                'Open /settings, press k, and update the API key.',
                'Press m in /settings to confirm the selected model belongs to that provider.',
                'Send the request again after saving the updated settings.',
            ),
        )
    if _contains_any(
        lower,
        (
            '429',
            'rate limit',
            'too many requests',
            'insufficient_quota',
            'quota',
            'billing',
        ),
    ):
        return ErrorGuidance(
            summary='The provider is rejecting more requests because of rate or billing limits.',
            steps=(
                'Wait a moment and retry.',
                'Switch to another model in /settings if you need to keep working right now.',
                'Check the provider dashboard for quota, spend, or billing problems.',
            ),
        )
    if _contains_any(
        lower,
        (
            '404',
            'model not found',
            'does not exist',
            'unknown model',
        ),
    ):
        return ErrorGuidance(
            summary='The configured model name is not available from the selected provider.',
            steps=(
                'Open /settings, press m, and pick a supported model.',
                'If you entered the model manually, include the correct provider prefix.',
            ),
        )
    if _contains_any(
        lower,
        (
            'connection',
            'connect error',
            'unreachable',
            'dns',
            'ssl',
            'certificate',
        ),
    ):
        return ErrorGuidance(
            summary='Grinta could not reach the model provider.',
            steps=(
                'Check your internet connection, VPN, proxy, or firewall rules.',
                'Retry after the connection is stable.',
            ),
        )
    if 'context' in lower and _contains_any(
        lower,
        ('length', 'window', 'limit', 'too many tokens'),
    ):
        return ErrorGuidance(
            summary='The request is larger than the model can accept.',
            steps=(
                'Retry with a shorter prompt or less pasted context.',
                'If you need the larger context, switch models in /settings.',
            ),
        )
    if 'budget' in lower:
        return ErrorGuidance(
            summary='The task budget blocked another model call.',
            steps=(
                'Open /settings, press b, and raise the budget.',
                'Use 0 if you want to remove the per-task budget limit.',
                'Retry the request after saving the new budget.',
            ),
        )
    if _contains_any(lower, ('file not found', 'no such file', 'path does not exist')):
        return ErrorGuidance(
            summary='The requested file or path was not available in the current project.',
            steps=(
                'Double-check the path and make sure the file still exists.',
                'If you moved the project, reopen grinta from the correct directory and retry.',
            ),
        )
    if _contains_any(lower, ('permission denied', 'access is denied', 'forbidden', '403')):
        return ErrorGuidance(
            summary='The current account or filesystem permissions are blocking the action.',
            steps=(
                'Verify the API key has access to the selected model or endpoint.',
                'If this is a local file action, reopen grinta from a writable directory and retry.',
            ),
        )
    if 'initialization failed' in lower:
        return ErrorGuidance(
            summary='Startup did not complete successfully.',
            steps=(
                'Restart grinta to try the bootstrap flow again.',
                'If it fails again, use the detail above to inspect the specific exception.',
            ),
        )
    return None


def _build_recovery_text(guidance: ErrorGuidance) -> Text:
    """Render a guidance block for the error panel."""
    recovery = Text()
    recovery.append('What you can try\n', style='yellow bold')
    recovery.append(guidance.summary, style='yellow')
    if guidance.steps:
        recovery.append('\n', style='yellow')
    for index, step in enumerate(guidance.steps, start=1):
        recovery.append(f'{index}. {step}', style='yellow')
        if index < len(guidance.steps):
            recovery.append('\n', style='yellow')
    return recovery


def _build_error_panel(
    error_text: str,
    *,
    title: str = 'Error',
    accent_style: str = 'red',
) -> Panel:
    """Render a structured error panel with recovery guidance when available."""
    summary, detail = _split_error_text(error_text)
    body_parts: list[Any] = [Text(summary, style=f'{accent_style} bold')]
    if detail:
        body_parts.append(Text(detail, style=f'{accent_style} dim'))

    guidance = _error_guidance(error_text)
    if guidance is not None:
        body_parts.append(_build_recovery_text(guidance))

    panel_title = Text(title.strip() or 'Error', style=f'{accent_style} bold')
    return Panel(
        Group(*body_parts),
        title=panel_title,
        border_style=accent_style,
        padding=(0, 1),
    )


def _system_message_style(title: str) -> tuple[str, str]:
    """Return a stable icon/color pair for non-agent status messages."""
    normalized = title.strip().lower()
    if normalized == 'warning':
        return '⚠', 'yellow'
    if normalized == 'autonomy':
        return '⚙', 'magenta'
    if normalized == 'status':
        return '●', 'blue'
    if normalized == 'settings':
        return '⚙', 'cyan'
    if 'timeout' in normalized:
        return '⏱', 'yellow'
    return 'ℹ', 'cyan'


# -- Tool call display helpers ------------------------------------------------

_TOOL_DISPLAY = {
    'execute_bash': ('$', 'cyan', 'command'),
    'str_replace_editor': ('✏', 'yellow', 'edit'),
    'create': ('✏', 'yellow', 'create'),
    'create_file': ('✏', 'yellow', 'create'),
    'view': ('👁', 'blue', 'view'),
    'replace_text': ('✏', 'yellow', 'edit'),
    'insert_text': ('✏', 'yellow', 'insert'),
    'undo_edit': ('↩', 'yellow', 'undo'),
}


def _friendly_tool_name(tool_name: str) -> str:
    """Convert an internal tool name to a user-friendly label."""
    info = _TOOL_DISPLAY.get(tool_name)
    if info:
        return info[2]
    # Fallback: strip common prefixes and snake_case → spaces.
    name = tool_name.replace('_', ' ').strip()
    return name or 'tool'


def _extract_tool_hint(partial_json: str) -> str:
    """Try to extract a readable hint from partial tool call JSON.

    Returns a short string like ``command: git status`` or ``path: src/main.py``
    when enough of the JSON has streamed. Returns '' if nothing useful yet.
    """
    import json as _json

    # First try a full parse (arguments may already be complete).
    try:
        args = _json.loads(partial_json)
        if isinstance(args, dict):
            parts: list[str] = []
            if 'command' in args:
                parts.append(f'$ {args["command"]}')
            if 'path' in args:
                parts.append(args['path'])
            return '\n'.join(parts) if parts else ''
    except (ValueError, TypeError):
        pass

    # Fallback: regex extraction for partially-streamed keys.
    hints: list[str] = []
    import re as _re

    m = _re.search(r'"command"\s*:\s*"([^"]*)', partial_json)
    if m:
        hints.append(f'$ {m.group(1)}')
    m = _re.search(r'"path"\s*:\s*"([^"]*)', partial_json)
    if m:
        hints.append(m.group(1))
    return '\n'.join(hints)


class CLIEventRenderer:
    """Bridges EventStream → live rich layout.

    Operates in two modes:

    * **Live mode** (during an agent turn): a Rich ``Live`` display is active
      and the renderer continuously redraws the streaming panel, reasoning
      spinner, and HUD footer.
    * **Static mode** (idle / prompt): no ``Live`` display.  Output is printed
      once via ``console.print()`` so prompt_toolkit can own the terminal for
      user input without any contention.
    """

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
        self._live: Live | None = None
        self._streaming_accumulated = ''
        self._streaming_final = False
        self._current_state: AgentState | None = None
        self._state_event = asyncio.Event()
        self._subscribed = False
        self._max_budget = max_budget
        self._pending_events: deque[Any] = deque()
        self._budget_warned_80 = False
        self._budget_warned_100 = False
        # Per-turn metric snapshots (used to compute deltas at turn completion)
        self._turn_start_cost: float = 0.0
        self._turn_start_tokens: int = 0
        self._turn_start_calls: int = 0
        # Items queued during Live mode; flushed as static output on stop_live.
        self._live_items: list[Any] = []

    @property
    def current_state(self) -> AgentState | None:
        return self._current_state

    @property
    def streaming_preview(self) -> str:
        return self._streaming_accumulated

    @property
    def budget_warned_80(self) -> bool:
        return self._budget_warned_80

    @property
    def budget_warned_100(self) -> bool:
        return self._budget_warned_100

    @property
    def pending_event_count(self) -> int:
        return len(self._pending_events)

    # -- Live lifecycle (per agent turn) -----------------------------------

    def start_live(self) -> None:
        """Create and start a Rich Live display for the current agent turn."""
        if self._live is not None:
            return
        self._live_items.clear()
        live = Live(
            self,
            console=self._console,
            auto_refresh=False,
            transient=True,  # erases on stop — we print final output ourselves
        )
        live.start()
        self._live = live
        self.refresh()

    def stop_live(self) -> None:
        """Stop the Rich Live display and flush buffered items as static output."""
        live = self._live
        if live is None:
            return
        self._live = None
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed', exc_info=True)
        # Print all items that accumulated during the live phase as permanent
        # static output so the transcript persists in the scrollback.
        for item in self._live_items:
            self._console.print(item)
        self._live_items.clear()
        self._hud.render_line(self._console)

    def refresh(self) -> None:
        """Redraw the Live display if active."""
        if self._live is not None:
            self._live.update(self, refresh=True)

    async def handle_event(self, event: Any) -> None:
        self._process_event_data(event)
        self.refresh()

    def reset_subscription(self) -> None:
        self._subscribed = False

    @contextmanager
    def suspend_live(self):
        """Stop/start Live around a block (fallback for non-interactive input)."""
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

    def begin_turn(self) -> None:
        """Snapshot metrics and mark the agent as running."""
        self._current_state = AgentState.RUNNING
        self._hud.update_ledger('Healthy')
        self._state_event.clear()
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
        self._live_items.clear()
        self._clear_streaming_preview()
        self._reasoning.stop()
        self.refresh()

    def add_user_message(self, text: str) -> None:
        """Print a user message. Always printed statically (prompt is idle)."""
        msg = Text()
        msg.append('\n❯ ', style='bold cyan')
        msg.append(text, style='bold')
        self._console.print(msg)

    def add_system_message(self, text: str, *, title: str = 'Info') -> None:
        lower_title = title.strip().lower()
        if lower_title == 'error':
            self._print_or_buffer(_build_error_panel(text, title='Error'))
            self._hud.update_ledger('Error')
            return
        if 'timeout' in lower_title:
            self._print_or_buffer(
                _build_error_panel(text, title=title, accent_style='yellow')
            )
            self._hud.update_ledger('Error')
            return
        if lower_title == 'warning':
            icon, color = _system_message_style(title)
            warning = Text()
            warning.append(f'  {icon} {title}: ', style=f'bold {color}')
            warning.append(text, style=color)
            self._print_or_buffer(warning)
            return

        icon, color = _system_message_style(title)
        message = Text()
        message.append(f'  {icon} {title}: ', style=f'bold {color}')
        message.append(text, style='dim' if color == 'cyan' else color)
        self._print_or_buffer(message)

    def add_markdown_block(self, title: str, text: str) -> None:
        self._print_or_buffer(
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
        """Called from the EventStream's delivery thread pool.

        Appends the event to a thread-safe deque for later processing.
        NO terminal writes happen here — all rendering is done by
        ``drain_events()`` on the main thread.  This avoids two threads
        (delivery pool + Live auto-refresh timer) fighting over stdout.
        """
        self._pending_events.append(event)
        # Wake the main-thread waiter so it drains promptly.
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def drain_events(self) -> None:
        """Process all queued events and refresh.

        MUST be called from
        the main thread (the one that owns the Live display).

        Always refreshes even when no events were queued so that
        time-based widgets (e.g. the Thinking… timer) stay up to date.
        """
        while self._pending_events:
            event = self._pending_events.popleft()
            self._process_event_data(event)
        self.refresh()

    def _process_event_data(self, event: Any) -> None:
        """Update internal state for one event.  Does NOT call refresh()."""
        if isinstance(event, _SKIP_ACTIONS) or isinstance(event, _SKIP_OBSERVATIONS):
            return

        self._update_metrics(event)

        source = getattr(event, 'source', None)

        if isinstance(event, Action) and source == EventSource.AGENT:
            self._handle_agent_action(event)
            return

        if isinstance(event, Observation):
            self._handle_observation(event)
            return

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        # During Live mode, show the last few buffered items plus
        # any active streaming panel and reasoning spinner.
        body_items = self._live_items[-12:]
        if self._streaming_accumulated:
            body_items.append(self._render_streaming_preview())
        if self._reasoning.active:
            body_items.append(self._reasoning.renderable())
        if not body_items:
            body_items.append(Text(''))

        layout = Layout()
        layout.split_column(
            Layout(Group(*body_items), ratio=1, name='body'),
            Layout(self._hud, size=1, name='footer'),
        )
        yield layout

    # -- action handlers ---------------------------------------------------

    def _handle_agent_action(self, action: Action) -> None:
        if isinstance(action, StreamingChunkAction):
            self._handle_streaming_chunk(action)
            return

        if isinstance(action, MessageAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            if action.content.strip():
                # Show file/image attachment indicators
                file_urls = getattr(action, 'file_urls', None) or []
                image_urls = getattr(action, 'image_urls', None) or []
                attachments: list[Any] = []
                if file_urls:
                    attachments.append(Text(f'  📎 {len(file_urls)} file(s) attached', style='dim'))
                if image_urls:
                    attachments.append(Text(f'  🖼️  {len(image_urls)} image(s) attached', style='dim'))

                self._append_history(
                    Panel(
                        Markdown(action.content),
                        title='[bold green]grinta[/bold green]',
                        border_style='green',
                        padding=(0, 1),
                    )
                )
                for att in attachments:
                    self._append_history(att)
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
            self._clear_streaming_preview()
            cmd_display = action.command
            if len(cmd_display) > 120:
                cmd_display = cmd_display[:117] + '…'
            self._append_history(
                Text(f'  ⚡ $ {cmd_display}', style='bold cyan'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Running: {cmd_display}')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        if isinstance(action, FileEditAction):
            self._clear_streaming_preview()
            op = getattr(action, 'command', 'edit')
            self._append_history(
                Text(f'  ✏️  {op}: {action.path}', style='bold yellow'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Editing: {action.path}')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        if isinstance(action, FileWriteAction):
            self._clear_streaming_preview()
            content = getattr(action, 'content', '')
            line_count = content.count('\n') + 1 if content else 0
            suffix = f' ({line_count} lines)' if line_count > 0 else ''
            self._append_history(
                Text(f'  ✏️  write: {action.path}{suffix}', style='bold yellow'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Writing: {action.path}')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        if isinstance(action, RecallAction):
            self._clear_streaming_preview()
            query = getattr(action, 'query', '')
            label = f'Recalling: {query}' if query else 'Recalling context…'
            self._append_history(
                Text(f'  📚 {label}', style='dim blue'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(label)
            self.refresh()
            return

        # -- File read --------------------------------------------------------
        if isinstance(action, FileReadAction):
            self._clear_streaming_preview()
            path = getattr(action, 'path', '')
            self._append_history(
                Text(f'  👁  read: {path}', style='bold blue'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Reading: {path}')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        # -- MCP tool call ----------------------------------------------------
        if isinstance(action, MCPAction):
            self._clear_streaming_preview()
            name = getattr(action, 'name', 'tool')
            self._append_history(
                Text(f'  🔧 mcp: {name}', style='bold magenta'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'MCP: {name}')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        # -- Browser ----------------------------------------------------------
        if isinstance(action, BrowseInteractiveAction):
            self._clear_streaming_preview()
            self._append_history(
                Text('  🌐 browsing…', style='bold blue'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action('Browsing')
            thought = getattr(action, 'thought', '')
            if thought:
                self._reasoning.update_thought(thought)
            self.refresh()
            return

        # -- Code navigation --------------------------------------------------
        if isinstance(action, LspQueryAction):
            self._clear_streaming_preview()
            cmd = getattr(action, 'command', 'query')
            file = getattr(action, 'file', '')
            symbol = getattr(action, 'symbol', '')
            label = f'{cmd}: {symbol}' if symbol else f'{cmd}: {file}'
            self._append_history(
                Text(f'  🔍 code nav: {label}', style='bold blue'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Code nav: {label}')
            self.refresh()
            return

        # -- Task tracking ----------------------------------------------------
        if isinstance(action, TaskTrackingAction):
            cmd = getattr(action, 'command', 'update')
            self._append_history(
                Text(f'  📋 tasks: {cmd}', style='dim cyan'),
            )
            self.refresh()
            return

        # -- Context condensation ---------------------------------------------
        if isinstance(action, CondensationAction):
            self._append_history(
                Text('  🗜️  compressing context…', style='dim'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action('Compressing context')
            self.refresh()
            return

        # -- Progress signal --------------------------------------------------
        if isinstance(action, SignalProgressAction):
            note = getattr(action, 'progress_note', '')
            if note:
                self._append_history(
                    Text(f'  📡 {note}', style='cyan'),
                )
            self.refresh()
            return

        # -- Terminal session -------------------------------------------------
        if isinstance(action, TerminalRunAction):
            self._clear_streaming_preview()
            cmd = getattr(action, 'command', '')
            cmd_display = cmd[:100] + '…' if len(cmd) > 100 else cmd
            self._append_history(
                Text(f'  💻 terminal: {cmd_display}', style='bold cyan'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Terminal: {cmd_display}')
            self.refresh()
            return

        if isinstance(action, TerminalInputAction):
            inp = getattr(action, 'input', '')
            inp_display = inp[:60] + '…' if len(inp) > 60 else inp
            self._append_history(
                Text(f'  💻 terminal input: {inp_display}', style='dim cyan'),
            )
            self.refresh()
            return

        # -- Delegation -------------------------------------------------------
        if isinstance(action, DelegateTaskAction):
            self._clear_streaming_preview()
            desc = getattr(action, 'task_description', '')
            desc_display = desc[:80] + '…' if len(desc) > 80 else desc
            self._append_history(
                Text(f'  🔀 delegating: {desc_display}', style='bold magenta'),
            )
            self._ensure_reasoning()
            self._reasoning.update_action(f'Delegating: {desc_display}')
            self.refresh()
            return

        # -- Playbook finish --------------------------------------------------
        if isinstance(action, PlaybookFinishAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            thought = getattr(action, 'final_thought', '') or getattr(action, 'thought', '')
            if thought:
                self._append_history(
                    Text(f'  ✅ {thought[:120]}', style='green'),
                )
            else:
                self._append_history(
                    Text('  ✅ Task complete', style='green'),
                )
            self.refresh()
            return

        # -- Escalation to human ----------------------------------------------
        if isinstance(action, EscalateToHumanAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            reason = getattr(action, 'reason', '')
            help_needed = getattr(action, 'specific_help_needed', '')
            body_parts: list[Any] = []
            if reason:
                body_parts.append(Text(reason, style='yellow'))
            if help_needed:
                body_parts.append(Text(f'Help needed: {help_needed}', style='yellow bold'))
            self._append_history(
                Panel(
                    Group(*body_parts) if body_parts else Text('Agent needs your help', style='yellow'),
                    title='[bold yellow]🆘 Escalation[/bold yellow]',
                    border_style='yellow',
                    padding=(0, 1),
                )
            )
            self.refresh()
            return

        # -- Clarification request --------------------------------------------
        if isinstance(action, ClarificationRequestAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            question = getattr(action, 'question', '')
            options = getattr(action, 'options', []) or []
            body_parts: list[Any] = []
            if question:
                body_parts.append(Text(question, style='yellow'))
            for i, opt in enumerate(options, 1):
                body_parts.append(Text(f'  {i}. {opt}', style='yellow dim'))
            self._append_history(
                Panel(
                    Group(*body_parts) if body_parts else Text('Agent has a question', style='yellow'),
                    title='[bold yellow]❓ Clarification needed[/bold yellow]',
                    border_style='yellow',
                    padding=(0, 1),
                )
            )
            self.refresh()
            return

        # -- Uncertainty signal -----------------------------------------------
        if isinstance(action, UncertaintyAction):
            concerns = getattr(action, 'specific_concerns', []) or []
            info_needed = getattr(action, 'requested_information', '')
            body_parts: list[Any] = []
            for concern in concerns[:5]:
                body_parts.append(Text(f'• {concern}', style='yellow'))
            if info_needed:
                body_parts.append(Text(f'Needs: {info_needed}', style='yellow dim'))
            if body_parts:
                self._append_history(
                    Panel(
                        Group(*body_parts),
                        title='[bold yellow]⚠️  Uncertain[/bold yellow]',
                        border_style='yellow',
                        padding=(0, 1),
                    )
                )
            self.refresh()
            return

        # -- Proposal with options --------------------------------------------
        if isinstance(action, ProposalAction):
            self._reasoning.stop()
            self._clear_streaming_preview()
            options = getattr(action, 'options', []) or []
            recommended = getattr(action, 'recommended', 0)
            rationale = getattr(action, 'rationale', '')
            body_parts: list[Any] = []
            if rationale:
                body_parts.append(Text(rationale, style='cyan'))
            for i, opt in enumerate(options):
                label = opt.get('name', opt.get('title', f'Option {i + 1}'))
                desc = opt.get('description', '')
                marker = ' ★' if i == recommended else ''
                body_parts.append(Text(f'  {i + 1}. {label}{marker}', style='bold cyan'))
                if desc:
                    body_parts.append(Text(f'     {desc}', style='cyan dim'))
            self._append_history(
                Panel(
                    Group(*body_parts) if body_parts else Text('Agent has a proposal', style='cyan'),
                    title='[bold cyan]💡 Proposal[/bold cyan]',
                    border_style='cyan',
                    padding=(0, 1),
                )
            )
            self.refresh()
            return

        self.refresh()

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        raw = action.accumulated

        # Tool call argument streaming: show progress in reasoning panel
        # instead of the content preview (avoids raw JSON in the preview).
        if action.is_tool_call:
            tool_name = action.tool_call_name or 'tool'
            friendly = _friendly_tool_name(tool_name)
            self._ensure_reasoning()
            self._reasoning.update_action(f'Preparing {friendly}…')
            # Try to extract useful info from partial JSON args
            hint = _extract_tool_hint(raw)
            if hint:
                self._reasoning.set_streaming_thought(hint)
            self.refresh()
            return

        # Route <think> content to the reasoning display so the user sees
        # the model's chain-of-thought in real time.
        think_match = _THINK_EXTRACT_RE.search(raw)
        if think_match:
            thinking_text = think_match.group(1)
            if thinking_text.strip():
                self._ensure_reasoning()
                self._reasoning.set_streaming_thought(thinking_text)
            # Strip thinking from the streaming preview.
            display_text = _THINK_STRIP_RE.sub('', raw).strip()
            self._streaming_accumulated = display_text
        else:
            self._streaming_accumulated = raw

        self._streaming_final = action.is_final
        if action.is_final:
            self._hud.state.llm_calls += 1
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
            success = exit_code == 0
            command_display = self._format_command_display(getattr(obs, 'command', ''))

            # Compact display for successful commands with short output
            if success and len(output) < 500:
                body_parts: list[Any] = [Text(f'  $ {command_display}', style='cyan')]
                if output.strip():
                    body_parts.append(
                        Syntax(output.rstrip(), 'text', word_wrap=True, theme='monokai')
                    )
                else:
                    body_parts.append(Text('  ✓ done', style='green dim'))
                self._append_history(Group(*body_parts))
                return

            # Expanded display for failures or long output
            header_style = 'green' if success else 'red'
            header = f'command · exit {exit_code}' if exit_code is not None else 'command output'
            truncated = len(output) > 4000
            display_output = output[:4000]
            body_parts: list[Any] = [Text(f'$ {command_display}', style='cyan')]
            if display_output:
                body_parts.append(
                    Syntax(display_output, 'text', word_wrap=True, theme='monokai')
                )
            else:
                body_parts.append(Text('(no output)', style='dim'))
            if truncated:
                body_parts.append(
                    Text(
                        f'\n⚠ Truncated ({len(output):,} chars, showing 4K)',
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
            self._append_history(
                _build_error_panel(error_content),
            )
            self._hud.update_ledger('Error')
            return

        if isinstance(obs, UserRejectObservation):
            content = getattr(obs, 'content', '')
            if content:
                self._append_history(Text(f'  ✗ Rejected: {content}', style='yellow'))
            else:
                self._append_history(Text('  ✗ Action rejected.', style='yellow'))
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
            # The next agent step will call the LLM — show activity indicator
            # so the user doesn't think the agent is stuck.
            self._ensure_reasoning()
            self._reasoning.update_action('Thinking…')
            self.refresh()
            return

        if isinstance(obs, StatusObservation):
            content = getattr(obs, 'content', '')
            if content:
                self._append_history(Text(f'  ℹ {content}', style='dim'))
            return

        # -- File read result -------------------------------------------------
        if isinstance(obs, FileReadObservation):
            self._reasoning.stop()
            path = getattr(obs, 'path', '')
            content = getattr(obs, 'content', '')
            lines = content.count('\n') + 1 if content else 0
            self._append_history(
                Text(f'  👁  read {path} ({lines} lines)', style='dim blue'),
            )
            return

        # -- MCP tool result --------------------------------------------------
        if isinstance(obs, MCPObservation):
            self._reasoning.stop()
            name = getattr(obs, 'name', 'tool')
            content = getattr(obs, 'content', '')
            content_preview = content[:200].strip() if content else ''
            if content_preview:
                body_parts: list[Any] = [
                    Text(f'  🔧 {name}', style='magenta'),
                    Syntax(content_preview, 'text', word_wrap=True, theme='monokai'),
                ]
                if len(content) > 200:
                    body_parts.append(Text(f'  … ({len(content):,} chars total)', style='dim'))
                self._append_history(Group(*body_parts))
            else:
                self._append_history(Text(f'  🔧 {name} ✓', style='dim magenta'))
            return

        # -- Terminal output --------------------------------------------------
        if isinstance(obs, TerminalObservation):
            self._reasoning.stop()
            session_id = getattr(obs, 'session_id', '')
            content = getattr(obs, 'content', '')
            if content.strip():
                display = content[:2000]
                body_parts: list[Any] = [
                    Syntax(display, 'text', word_wrap=True, theme='monokai'),
                ]
                if len(content) > 2000:
                    body_parts.append(
                        Text(f'  … ({len(content):,} chars total)', style='dim')
                    )
                self._append_history(
                    Panel(
                        Group(*body_parts),
                        title=f'[cyan]💻 terminal[/cyan]',
                        border_style='bright_black',
                        padding=(0, 1),
                    )
                )
            return

        # -- LSP / code navigation result -------------------------------------
        if isinstance(obs, LspQueryObservation):
            self._reasoning.stop()
            content = getattr(obs, 'content', '')
            available = getattr(obs, 'available', True)
            if not available:
                self._append_history(
                    Text('  🔍 code nav: not available', style='dim yellow'),
                )
            elif content:
                preview = content[:300].strip()
                self._append_history(
                    Text(f'  🔍 code nav result ({len(content)} chars)', style='dim blue'),
                )
            return

        # -- Server ready -----------------------------------------------------
        if isinstance(obs, ServerReadyObservation):
            url = getattr(obs, 'url', '')
            port = getattr(obs, 'port', '')
            health = getattr(obs, 'health_status', 'unknown')
            label = url or f'port {port}'
            self._append_history(
                Text(f'  🚀 Server ready at {label} ({health})', style='bold green'),
            )
            return

        # -- Success ----------------------------------------------------------
        if isinstance(obs, SuccessObservation):
            content = getattr(obs, 'content', '')
            self._append_history(
                Text(f'  ✓ {content}' if content else '  ✓ Done', style='green'),
            )
            return

        # -- Recall failure ---------------------------------------------------
        if isinstance(obs, RecallFailureObservation):
            error_msg = getattr(obs, 'error_message', '')
            recall_type = getattr(obs, 'recall_type', None)
            label = str(recall_type.value) if recall_type else 'recall'
            self._append_history(
                Text(
                    f'  ⚠ {label} failed: {error_msg}' if error_msg else f'  ⚠ {label} failed',
                    style='yellow',
                )
            )
            return

        # -- File download ----------------------------------------------------
        if isinstance(obs, FileDownloadObservation):
            path = getattr(obs, 'file_path', '')
            self._append_history(
                Text(f'  📥 Downloaded: {path}', style='green'),
            )
            return

        # -- Delegation result ------------------------------------------------
        if isinstance(obs, DelegateTaskObservation):
            self._reasoning.stop()
            success = getattr(obs, 'success', True)
            error = getattr(obs, 'error_message', '')
            if success:
                self._append_history(
                    Text('  🔀 Delegation completed ✓', style='green'),
                )
            else:
                self._append_history(
                    Text(f'  🔀 Delegation failed: {error}' if error else '  🔀 Delegation failed', style='red'),
                )
            return

        # -- Task tracking result ---------------------------------------------
        if isinstance(obs, TaskTrackingObservation):
            cmd = getattr(obs, 'command', '')
            self._append_history(
                Text(f'  📋 Tasks updated ({cmd})', style='dim cyan'),
            )
            return

        # -- Context condensation result --------------------------------------
        if isinstance(obs, AgentCondensationObservation):
            self._append_history(
                Text('  🗜️  Context compressed', style='dim'),
            )
            return

        # -- Progress signal --------------------------------------------------
        if isinstance(obs, SignalProgressObservation):
            note = getattr(obs, 'progress_note', '')
            if note:
                self._append_history(Text(f'  📡 {note}', style='dim cyan'))
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
        previous_state = self._current_state
        self._current_state = state
        # Signal waiters on the main event loop (asyncio.Event is not thread-safe).
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

        # Update HUD ledger indicator on terminal states.
        if state in (AgentState.ERROR, AgentState.REJECTED):
            self._hud.update_ledger('Error')
        elif state == AgentState.AWAITING_USER_CONFIRMATION:
            self._hud.update_ledger('Review')
        elif state == AgentState.AWAITING_USER_INPUT:
            self._hud.update_ledger('Ready')
        elif state == AgentState.PAUSED:
            self._hud.update_ledger('Paused')
        elif state in (AgentState.FINISHED, AgentState.STOPPED):
            self._hud.update_ledger('Idle')
        elif state == AgentState.RUNNING:
            self._hud.update_ledger('Healthy')

        if state == AgentState.AWAITING_USER_CONFIRMATION:
            self._reasoning.stop()
            self._clear_streaming_preview()
            if previous_state != state:
                self._append_history(
                    Text(
                        '  ⚠ Approval required — review the pending action.',
                        style='yellow',
                    )
                )
            self.refresh()
            return

        if state == AgentState.AWAITING_USER_INPUT:
            self._reasoning.stop()
            self._clear_streaming_preview()
            self.refresh()
            return

        if state == AgentState.PAUSED:
            self._reasoning.stop()
            self._clear_streaming_preview()
            if previous_state != state:
                self._append_history(
                    Text('  ⏸ Paused — send guidance to continue.', style='yellow')
                )
            return

        if state == AgentState.FINISHED:
            self._reasoning.stop()
            self._clear_streaming_preview()
            stats = self._turn_stats_text()
            self._append_history(
                Text(f'  ✓ Done.{stats}', style='green'),
            )
            return

        if state == AgentState.ERROR:
            self._reasoning.stop()
            self._clear_streaming_preview()
            stats = self._turn_stats_text()
            self._append_history(
                Text(
                    f'  ✗ Error — send a follow-up to retry.{stats}',
                    style='red dim',
                ),
            )
            return

        if state == AgentState.REJECTED:
            self._reasoning.stop()
            self._clear_streaming_preview()
            self._append_history(
                Text('  ✗ Action rejected — adjust the task and retry.', style='yellow')
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
        """Add a renderable: buffer during Live, print otherwise."""
        self._print_or_buffer(renderable)

    def _print_or_buffer(self, renderable: Any) -> None:
        """Print statically if idle, or buffer for Live if active."""
        if self._live is not None:
            self._live_items.append(renderable)
            self.refresh()
        else:
            self._console.print(renderable)

    def _clear_streaming_preview(self) -> None:
        self._streaming_accumulated = ''
        self._streaming_final = False
        self.refresh()

    def _render_streaming_preview(self) -> Any:
        body: list[Any] = [Markdown(self._streaming_accumulated or '')]
        if not self._streaming_final:
            body.append(Text('▌', style='bold green'))
        return Panel(
            Group(*body),
            title='[bold green]grinta[/bold green]',
            border_style='green',
            padding=(0, 1),
        )

    @staticmethod
    def _format_command_display(command: str, *, limit: int = 96) -> str:
        display = ' '.join(command.split())
        if not display:
            return '(empty command)'
        if len(display) > limit:
            return display[: limit - 1] + '…'
        return display

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
            self._print_or_buffer(
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
            self._print_or_buffer(
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
