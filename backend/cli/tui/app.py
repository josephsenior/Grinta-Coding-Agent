"""Grinta TUI — Textual Application screen and widgets."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.screen import Screen

from backend.cli.config_manager import AppConfig
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)
from backend.cli.tui._app_renderer_action_handlers_mixin import (
    _AppRendererActionHandlersMixin,  # noqa: F401
)
from backend.cli.tui._app_renderer_display_mixin import (
    _AppRendererDisplayMixin,  # noqa: F401
)
from backend.cli.tui._app_renderer_event_processor_mixin import (
    _AppRendererEventProcessorMixin,  # noqa: F401
)

# ── TUIRenderer mixin imports ──
from backend.cli.tui._app_renderer_live_mixin import _AppRendererLiveMixin  # noqa: F401
from backend.cli.tui._app_renderer_terminal_mixin import (
    _AppRendererTerminalMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_actions_mixin import (
    _AppScreenActionsMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_communicate_mixin import (
    _AppScreenCommunicateMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_input_mixin import _AppScreenInputMixin  # noqa: F401

# ── GrintaScreen mixin imports ──
from backend.cli.tui._app_screen_lifecycle_mixin import (
    _AppScreenLifecycleMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_messages_mixin import (
    _AppScreenMessagesMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_settings_mixin import (
    _AppScreenSettingsMixin,  # noqa: F401
)
from backend.cli.tui._app_screen_state_mixin import _AppScreenStateMixin  # noqa: F401
from backend.cli.tui._app_screen_welcome_mixin import (
    _AppScreenWelcomeMixin,  # noqa: F401
)


class GrintaScreen(
    _AppScreenLifecycleMixin,
    _AppScreenStateMixin,
    _AppScreenMessagesMixin,
    _AppScreenCommunicateMixin,
    _AppScreenWelcomeMixin,
    _AppScreenSettingsMixin,
    _AppScreenInputMixin,
    _AppScreenActionsMixin,
    Screen,
):
    """Main TUI screen — Mission Control layout."""

    CSS_PATH = 'styles.tcss'
    BINDINGS = [
        Binding('ctrl+c', 'copy_or_interrupt', 'Copy/Interrupt', show=True),
        Binding('ctrl+shift+c', 'copy_transcript', 'Copy Transcript', show=True),
        Binding('escape', 'interrupt_agent', 'Interrupt', show=False),
        Binding('ctrl+l', 'clear_transcript', 'Clear', show=True),
        Binding('ctrl+space', 'complete_command', 'Complete', show=False),
        Binding('ctrl+z', 'suspend', 'Suspend', show=False),
        Binding('enter', 'submit_input', 'Send', show=False, priority=True),
        Binding('pageup', 'scroll_up', 'Scroll Up', show=False),
        Binding('pagedown', 'scroll_down', 'Scroll Down', show=False),
        Binding('home', 'scroll_home', 'Top', show=False),
        Binding('end', 'scroll_end', 'Bottom', show=False),
        Binding('ctrl+b', 'toggle_sidebar', 'Toggle Sidebar', show=True),
        Binding('f1', 'show_help', 'Help', show=True),
        Binding('ctrl+j', 'focus_next_card', 'Next Card', show=False, priority=True),
        Binding('ctrl+k', 'focus_prev_card', 'Prev Card', show=False, priority=True),
        Binding('ctrl+p', 'history_prev', 'History Prev', show=False),
        Binding('ctrl+n', 'history_next', 'History Next', show=False),
    ]
    _STATE_LABELS = {
        'starting': 'Starting…',
        'loading': 'Loading…',
        'running': 'Running',
        'retrying': 'Retrying',
        'backoff': 'Backoff',
        'awaiting_user_input': 'Ready',
        'paused': 'Paused',
        'stopped': 'Stopped',
        'finished': 'Finished',
        'rejected': 'Rejected',
        'error': 'Error',
        'awaiting_user_confirmation': 'Confirm',
        'user_confirmed': 'Confirmed',
        'user_rejected': 'Rejected',
        'rate_limited': 'Rate Limited',
    }
    _STATE_COLORS = {
        'starting': NAVY_WAITING,
        'loading': NAVY_WAITING,
        'running': NAVY_BRAND,
        'retrying': NAVY_WAITING,
        'backoff': NAVY_WAITING,
        'awaiting_user_input': NAVY_READY,
        'paused': NAVY_WAITING,
        'stopped': NAVY_TEXT_MUTED,
        'finished': NAVY_READY,
        'rejected': NAVY_ERROR,
        'error': NAVY_ERROR,
        'awaiting_user_confirmation': NAVY_WAITING,
        'user_confirmed': NAVY_READY,
        'user_rejected': NAVY_ERROR,
        'rate_limited': NAVY_WAITING,
    }
    _SLASH_HINTS = {
        '/help': '/help [--all|--search <term>|<command>]',
        '/clear': '/clear',
        '/settings': '/settings',
        '/sessions': '/sessions [list] [--limit N] [--search TERM] [--sort updated|created|events|cost|model] [--preview N|ID] [--delete N|ID ...]',
        '/resume': '/resume <N|session_id>',
        '/quit': '/quit',
    }
    _INPUT_HEIGHT_FRACTION = 0.3
    _MIN_INPUT_HEIGHT = 6
    _ACTION_TYPE_LABELS: dict[str, str] = {
        'CmdRunAction': 'Run Command',
        'FileWriteAction': 'Write File',
        'FileEditAction': 'Edit File',
        'FileReadAction': 'Read File',
        'FileEditActionMulti': 'Edit File',
        'MCPAction': 'MCP Tool',
        'BrowserToolAction': 'Browser',
        'DelegateTaskAction': 'Delegate',
        'MessageAction': 'Message',
        'FinishAction': 'Finish',
        'SystemMessageAction': 'System',
        'NoteAction': 'Note',
    }
    _RISK_LABELS: dict[str, tuple[str, str]] = {
        'UNKNOWN': ('Unknown', 'dim'),
        'LOW': ('Low', 'green'),
        'MEDIUM': ('Medium', 'yellow'),
        'HIGH': ('High', 'bold red'),
    }

    def __init__(
        self,
        config: AppConfig,
        console: Any,
        loop: asyncio.AbstractEventLoop,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        app: App,
    ) -> None:
        super().__init__()
        self._config = config
        self._rich_console = console
        self._loop = loop
        self._hud = hud
        self._reasoning = reasoning
        self._main_app = app
        self._renderer: TUIRenderer | None = None
        self._event_stream: Any | None = None
        self._controller: Any | None = None
        self._agent_task: asyncio.Task[Any] | None = None
        self._runtime_stub: Any = None
        self._memory_stub: Any = None
        self._agent_running = True
        self._input_lock = asyncio.Lock()
        self._bootstrapping: asyncio.Event | None = None
        self._bootstrap_task: asyncio.Task[Any] | None = None
        self._is_unmounted = False
        self._suggestion_matches: list[str] = []
        self._command_hint = ''
        self._phase_label = 'Ready'
        self._phase_started_at = time.monotonic()
        self._current_operation_summary = 'Idle'
        self._current_operation_meta = 'Waiting for activity'
        self._current_operation_active = False
        self._worker_summary = 'No delegated work'
        self._worker_meta = 'Idle'
        self._worker_active = False
        self._worker_has_error = False
        self._retry_summary = 'No retry activity'
        self._retry_meta = 'Idle'
        self._retry_active = False
        self._runtime_summary = 'No runtime notices'
        self._runtime_meta = 'Idle'
        self._runtime_active = False
        self._hud_tick = None
        self._command_history: list[str] = []
        self._history_index: int = -1
        self._welcome_visible = False
        self._active_communicate_card: Any | None = None


class TUIRenderer(
    _AppRendererLiveMixin,
    _AppRendererDisplayMixin,
    _AppRendererTerminalMixin,
    _AppRendererEventProcessorMixin,
    _AppRendererActionHandlersMixin,
):
    """Rich-driven renderer for Textual — manages history and real-time display."""

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        'create_file': ('Created', False),
        'replace_string': ('Edited', False),
        'multi_edit': ('Edited', False),
    }

    def __init__(
        self,
        console: Any,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        tui: GrintaScreen,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._tui = tui
        self._loop = loop
        self._event_stream: Any | None = None
        self._state_event = asyncio.Event()
        self._current_state: Any = None
        self._pending_events: deque[Any] = deque()
        self._pending_lock = threading.Lock()
        self._drain_scheduled = False
        self._pending_events_dropped = 0

        # History & Live state
        self._live_thinking_widget: Any | None = None
        self._live_response_widget: Any | None = None
        self._task_list: list[dict[str, Any]] = []
        self._last_sidebar_state: Any = None

        # Unit test compatibility
        self._history: list[Any] = []
        self._history_items_dropped: int = 0
        self._live_thinking: str = ''
        self._live_thinking_dirty: bool = False
        self._live_response: str = ''
        self._live_response_dirty: bool = False
        self._last_final_response_text: str = ''

        # Turn tracking for grouping tool calls by agent turn
        self._turn_count: int = 0
        self._in_agent_turn: bool = False
        self._tools_in_turn: int = 0
        self._turn_start_time: float = 0.0
        self._terminal_cards_by_session: dict[str, Any] = {}
        self._terminal_commands_by_session: dict[str, str] = {}
        self._pending_terminal_command: str | None = None
        self._pending_terminal_card: Any | None = None
        self._pending_shell_cards_by_command: dict[str, deque[Any]] = defaultdict(deque)
        self._active_worker_tasks: list[str] = []
        self._worker_recent_results: deque[str] = deque(maxlen=3)
        self._worker_completed: int = 0
        self._worker_failed: int = 0
        self._condensation_count: int = 0
        self._last_active_card: Any | None = None
        self._last_browser_action_card: Any | None = None
        self._last_browser_cmd: str = ''


# ── Re-exports for backward compatibility ──
from backend.cli.tui._app_constants import (  # noqa: F401
    _FILE_DIFF_AUTO_COLLAPSE_LINES,
    _TERMINAL_MOUSE_REPORT_RE,
    _TERMINAL_ORPHAN_PARAM_TOKEN_RE,
    _TUI_HISTORY_RENDER_LIMIT,
    _TUI_PENDING_EVENT_LIMIT,
    _WELCOME_FIGLET_CACHE,
    _WELCOME_FIGLET_FALLBACK,
    _WELCOME_SUGGESTIONS,
    _bounded_int_env,
    _tui_logger,
)
from backend.cli.tui._app_dialogs import (  # noqa: F401
    ConfirmWidget,
    GrintaAddMCPDialog,
    GrintaAddSkillDialog,
    GrintaConfirmDialog,
    GrintaHelpDialog,
    GrintaSessionsDialog,
    GrintaSettingsDialog,
)
from backend.cli.tui._app_helpers import (  # noqa: F401
    _count_text_lines,
    _count_unified_diff_changes,
    _encode_split_diff_contents,
    _encode_unified_diff_text,
    _extract_tagged_block,
    _format_diff_summary,
    _get_welcome_figlet,
    _join_secondary_parts,
    _numbered_diff_line,
    _render_thinking_with_diff,
    _rich_text,
    _sanitize_terminal_display_text,
    _should_collapse_file_diff,
    _split_combined_diff,
    _split_diff_opcode_rows,
    _strip_ansi,
    _strip_terminal_control_literals,
)
from backend.cli.tui._app_small_widgets import (  # noqa: F401
    HUD,
    InfoSidebar,
    InputBar,
    PromptTextArea,
    RendererDrainRequested,
    Transcript,
)
from backend.cli.tui._app_welcome_widgets import (  # noqa: F401
    CommunicatePromptWidget,
    WelcomeWidget,
)
