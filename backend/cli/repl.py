"""Async REPL — prompt_toolkit input loop integrated with the agent engine."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from rich.console import Console

from backend.cli._repl.run_helpers_mixin import RunHelpersMixin
from backend.cli._repl.session_lifecycle_mixin import SessionLifecycleMixin
from backend.cli._repl.slash_commands_mixin import SlashCommandsMixin
from backend.cli.config_manager import get_current_model
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import (
    CLR_AUTONOMY_BALANCED,
    CLR_AUTONOMY_FULL,
    CLR_AUTONOMY_SUPERVISED,
    CLR_BRAND,
    CLR_HUD_DETAIL,
    CLR_HUD_MODEL,
    CLR_META,
    CLR_MUTED_TEXT,
    CLR_SEP,
    CLR_STATE_RUNNING,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    CLR_THINKING_BORDER,
)
from backend.core.config import (
    AppConfig,
)
from backend.core.config import (
    load_app_config as load_app_config,  # re-exported for tests/back-compat
)
from backend.core.enums import AgentState
from backend.core.os_capabilities import OS_CAPS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.ledger.stream import EventStream


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# History file
# ---------------------------------------------------------------------------
_HISTORY_DIR = Path.home() / '.grinta'
_HISTORY_FILE = _HISTORY_DIR / 'history.txt'


@dataclass(frozen=True)
class SlashCommandSpec:
    """Metadata used by help text and prompt-toolkit completion."""

    name: str
    description: str
    usage: str
    aliases: tuple[str, ...] = ()
    #: Grouping key for `/help` (see `_HELP_SECTIONS_ORDER`).
    help_section: str = 'system'


@dataclass(frozen=True)
class ParsedSlashCommand:
    """A slash command tokenized without breaking Windows paths."""

    raw_name: str
    name: str
    args: tuple[str, ...]


class SlashCommandParseError(ValueError):
    """Raised when the user entered a malformed slash command."""


_AUTONOMY_LEVEL_HINTS = {
    'supervised': 'Always ask before actions',
    'balanced': 'Ask only for high-risk actions',
    'full': 'Run without confirmation prompts',
}
_SLASH_COMMANDS = (
    SlashCommandSpec(
        '/help',
        'Show commands and shortcuts',
        '/help [command]',
        aliases=('/?',),
        help_section='system',
    ),
    SlashCommandSpec(
        '/settings',
        'Open settings (model, API key, MCP)',
        '/settings',
        help_section='model',
    ),
    SlashCommandSpec(
        '/sessions', 'List past sessions', '/sessions', help_section='session'
    ),
    SlashCommandSpec(
        '/resume',
        'Resume a past session by index or ID',
        '/resume <N|id>',
        help_section='session',
    ),
    SlashCommandSpec(
        '/autonomy',
        'View or set autonomy (supervised/balanced/full)',
        '/autonomy [supervised|balanced|full]',
        help_section='model',
    ),
    SlashCommandSpec(
        '/model',
        'Show or switch the active model',
        '/model [provider/model]',
        help_section='model',
    ),
    SlashCommandSpec(
        '/compact',
        'Condense context to free token budget',
        '/compact',
        help_section='control',
    ),
    SlashCommandSpec(
        '/retry', 'Re-send the last message', '/retry', help_section='control'
    ),
    SlashCommandSpec(
        '/status',
        'Show the current HUD snapshot (use `verbose` for diagnostics)',
        '/status [verbose]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/cost',
        'Show running token & USD cost for this session',
        '/cost',
        help_section='control',
    ),
    SlashCommandSpec(
        '/diff',
        'Show workspace git changes',
        '/diff [--stat|--name-only|--patch] [path]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/think',
        'Toggle the optional `think` reasoning tool',
        '/think [on|off]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/checkpoint',
        'Save a manual checkpoint of the workspace',
        '/checkpoint [label]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/copy',
        'Copy last assistant message to system clipboard',
        '/copy',
        help_section='control',
    ),
    SlashCommandSpec(
        '/clear', 'Clear the visible transcript', '/clear', help_section='control'
    ),
    SlashCommandSpec(
        '/exit', 'Quit grinta', '/exit', aliases=('/quit',), help_section='system'
    ),
)

# Known models surfaced in `/model` tab-completion.
# provider/model pairs — provider shown as display_meta in the completer.
_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ('openai/gpt-4.1', 'OpenAI'),
    ('openai/gpt-4o', 'OpenAI'),
    ('openai/o4-mini', 'OpenAI'),
    ('anthropic/claude-opus-4-20250514', 'Anthropic'),
    ('anthropic/claude-sonnet-4-20250514', 'Anthropic'),
    ('anthropic/claude-haiku-4-20250514', 'Anthropic'),
    ('google/gemini-2.5-pro', 'Google'),
    ('google/gemini-2.5-flash', 'Google'),
    ('groq/meta-llama/llama-4-scout', 'Groq'),
    ('xai/grok-4.1-fast', 'xAI'),
    ('deepseek/deepseek-chat', 'DeepSeek'),
    ('openrouter/anthropic/claude-3.5-sonnet', 'OpenRouter'),
)
_COMMAND_ALIASES = {
    alias: spec.name for spec in _SLASH_COMMANDS for alias in spec.aliases
}
_COMMAND_NAMES = tuple(
    name for spec in _SLASH_COMMANDS for name in (spec.name, *spec.aliases)
)


def _ensure_history() -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


def _canonical_command_name(command: str) -> str:
    """Normalize slash-command aliases to a single canonical name."""
    lowered = command.lower()
    return _COMMAND_ALIASES.get(lowered, lowered)


def _split_command_words(text: str) -> tuple[str, ...]:
    """Split a REPL command line with quotes while preserving backslashes."""
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    in_word = False

    for char in text.strip():
        if char in {'"', "'"}:
            if quote == char:
                quote = None
                in_word = True
                continue
            if quote is None:
                quote = char
                in_word = True
                continue
        if char.isspace() and quote is None:
            if in_word:
                words.append(''.join(current))
                current = []
                in_word = False
            continue
        current.append(char)
        in_word = True

    if quote is not None:
        raise SlashCommandParseError(f'Unclosed {quote} quote in command.')
    if in_word:
        words.append(''.join(current))
    return tuple(words)


def _parse_slash_command(text: str) -> ParsedSlashCommand:
    """Parse and canonicalize a slash command line."""
    words = _split_command_words(text)
    if not words or not words[0].startswith('/'):
        raise SlashCommandParseError('Expected a slash command.')
    raw_name = words[0].lower()
    return ParsedSlashCommand(
        raw_name=raw_name,
        name=_canonical_command_name(raw_name),
        args=words[1:],
    )


def _iter_command_completion_entries() -> list[tuple[str, str]]:
    """Return slash commands plus aliases for prompt-toolkit completion."""
    entries: list[tuple[str, str]] = []
    for spec in _SLASH_COMMANDS:
        entries.append((spec.name, spec.description))
        entries.extend((alias, f'Alias for {spec.name}') for alias in spec.aliases)
    return entries


_HELP_SECTIONS_ORDER: tuple[tuple[str, str], ...] = (
    ('session', 'Session & history'),
    ('model', 'Model & configuration'),
    ('control', 'Context & control'),
    ('system', 'System'),
)


def _find_command_spec(command_name: str) -> SlashCommandSpec | None:
    normalized = command_name.strip().lower()
    if normalized and not normalized.startswith('/'):
        normalized = f'/{normalized}'
    canonical = _canonical_command_name(normalized)
    for spec in _SLASH_COMMANDS:
        if spec.name == canonical:
            return spec
    return None


def _help_for_specific_command(command_name: str) -> str:
    spec = _find_command_spec(command_name)
    if spec is None:
        suggestions = _closest_command_names(command_name)
        suffix = ''
        if suggestions:
            suffix = (
                '\n\nTry ' + ' or '.join(f'`{item}`' for item in suggestions) + '.'
            )
        return f'No help topic for `{command_name}`.{suffix}'
    detail_lines = [
        f'`{spec.usage}`',
        '',
        spec.description,
    ]
    if spec.aliases:
        detail_lines.extend(
            ['', 'Aliases: ' + ', '.join(f'`{alias}`' for alias in spec.aliases)]
        )
    return '\n'.join(detail_lines)


def _help_section_lines(specs: list['SlashCommandSpec']) -> list[str]:
    lines: list[str] = []
    for spec in specs:
        alias_text = (
            ' _(aliases: '
            + ', '.join(f'`{alias}`' for alias in spec.aliases)
            + ')_'
            if spec.aliases
            else ''
        )
        lines.append(f'- `{spec.usage}` — {spec.description}{alias_text}')
    return lines


_HELP_INPUT_TIPS: tuple[str, ...] = (
    '',
    '**Input tips**',
    '',
    '- `Tab` autocomplete slash commands and common arguments',
    '- `↑` / `↓` search prompt history',
    '- `Alt+Enter` insert a newline',
    '- `Ctrl+C` interrupt the current run',
)


def _build_help_markdown(command_name: str | None = None) -> str:
    """Build the slash-command help block from the shared command registry."""
    from collections import defaultdict

    if command_name:
        return _help_for_specific_command(command_name)

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    lines: list[str] = []
    first_section = True
    for section_key, title in _HELP_SECTIONS_ORDER:
        specs = by_section.get(section_key)
        if not specs:
            continue
        if not first_section:
            lines.append('')
        first_section = False
        lines.append(f'**{title}**')
        lines.append('')
        lines.extend(_help_section_lines(specs))

    lines.extend(_HELP_INPUT_TIPS)
    return '\n'.join(lines)


def _closest_command_names(command: str, *, limit: int = 2) -> list[str]:
    """Suggest the closest matching slash commands for typos."""
    matches = get_close_matches(command, _COMMAND_NAMES, n=limit, cutoff=0.5)
    suggestions: list[str] = []
    for match in matches:
        if match not in suggestions:
            suggestions.append(match)
    return suggestions


def _copy_to_system_clipboard(text: str) -> tuple[bool, str]:
    """Copy plain text to OS clipboard with multi-platform fallbacks."""
    if not text.strip():
        return False, 'No assistant reply available to copy yet.'

    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True, 'Copied last assistant reply to clipboard.'
    except Exception:
        pass

    candidates: list[list[str]] = []
    if OS_CAPS.is_windows:
        candidates = [['clip']]
    elif OS_CAPS.is_macos:
        candidates = [['pbcopy']]
    else:
        candidates = [
            ['wl-copy'],
            ['xclip', '-selection', 'clipboard'],
            ['xsel', '--clipboard', '--input'],
        ]

    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, input=text, text=True, check=True)
            return True, 'Copied last assistant reply to clipboard.'
        except Exception:
            continue

    return (
        False,
        'Clipboard copy failed. Install `pyperclip` (recommended) or a system clipboard tool and retry.',
    )


# Leaked bracket-param sequences (e.g. Windows Terminal / ConPTY) — often no ESC.
_ORPHAN_BRACKET_CSI = re.compile(
    r'\[+(?:\d+;){2,}[\d;:_\s-]*[OI]?(?=\[|$| |\Z)',
    re.MULTILINE,
)
# Bracketless leaked parameter chunks seen in some ConPTY/Cursor terminals:
# e.g. ``0;1;40;1_0;0;32;1_8;1;32;1_``.
_ORPHAN_PARAM_CHUNK_STREAM = re.compile(
    r'(?<![A-Za-z0-9])(?:\[?(?:\d+;){2,}\d+[OI]?_){2,}',
    re.MULTILINE,
)
_ORPHAN_PARAM_CHUNK_SINGLE = re.compile(
    r'(?<![A-Za-z0-9])\[?(?:\d+;){4,}\d+[OI]?_',
    re.MULTILINE,
)
# Well-formed 7-bit CSI and OSC (bell or ST-terminated).
_CSI_OSC_DCS = re.compile(
    r'(?:\x1B\][^\x07\x1B]*(?:\x07|\x1B\\))'
    r'|(?:\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))',
    re.DOTALL,
)


def _strip_leaked_terminal_artifacts(text: str) -> str:
    """Remove terminal escape/CSI leaks the host injects (e.g. after Ctrl+C + selection)."""
    if not text:
        return text
    out = text
    for _ in range(16):
        prev = out
        out = _CSI_OSC_DCS.sub('', out)
        out = _ORPHAN_BRACKET_CSI.sub('', out)
        out = _ORPHAN_PARAM_CHUNK_STREAM.sub('', out)
        out = _ORPHAN_PARAM_CHUNK_SINGLE.sub('', out)
        # focus in/out and similar two-letter CSI finals without a leading esc byte
        out = re.sub(r'\[+(?:O|I)+', '', out)
        if out == prev:
            break
    return out


def _looks_like_terminal_selection_noise(text: str) -> bool:
    """Best-effort: whole buffer is only leaked terminal control noise."""
    sample = (text or '').strip()
    if len(sample) < 8:
        return False
    cleaned = _strip_leaked_terminal_artifacts(sample)
    return not cleaned.strip()


def _attach_prompt_buffer_csi_sanitizer(session: Any) -> None:
    """Strip host-injected control-sequence text from the line buffer in real time.

    Without this, leaked ``[nn;...`` sequences from the terminal appear *in* the
    input line; filtering only on submit is too late for the user.
    """
    buf = getattr(session, 'default_buffer', None)
    if buf is None:
        return
    from prompt_toolkit.document import Document

    sinking = [False]

    def _on_text_changed(_: object) -> None:
        if sinking[0]:
            return
        current = buf.text
        clean = _strip_leaked_terminal_artifacts(current)
        if clean == current:
            return
        sinking[0] = True
        try:
            pos = min(buf.cursor_position, len(clean))
            buf.document = Document(clean, pos)
        finally:
            sinking[0] = False

    try:
        buf.on_text_changed += _on_text_changed
    except Exception:  # pragma: no cover
        logger.debug('Could not attach CSI sanitizer to prompt buffer', exc_info=True)


def _build_command_completer(
    load_session_suggestions: Callable[[], list[tuple[str, str]]] | None = None,
) -> Any:
    """Create the prompt-toolkit completer used by the interactive REPL."""
    from prompt_toolkit.completion import Completer, Completion

    session_loader = load_session_suggestions or (lambda: [])

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # type: ignore[override]
            del complete_event
            text_before_cursor = document.text_before_cursor.lstrip()
            if not text_before_cursor.startswith('/'):
                return

            has_trailing_space = document.text_before_cursor.endswith(' ')
            parts = text_before_cursor.split()
            if not parts:
                return

            command_token = parts[0].lower()
            if len(parts) == 1 and not has_trailing_space:
                prefix = command_token
                for name, description in _iter_command_completion_entries():
                    if name.startswith(prefix):
                        yield Completion(
                            name,
                            start_position=-len(prefix),
                            display_meta=description,
                        )
                return

            canonical_command = _canonical_command_name(command_token)
            argument_prefix = '' if has_trailing_space or len(parts) < 2 else parts[1]

            if canonical_command == '/autonomy':
                lowered_prefix = argument_prefix.lower()
                for level, description in _AUTONOMY_LEVEL_HINTS.items():
                    if level.startswith(lowered_prefix):
                        yield Completion(
                            level,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/model':
                lowered_prefix = argument_prefix.lower()
                for model_id, provider in _KNOWN_MODELS:
                    if lowered_prefix and not model_id.startswith(lowered_prefix):
                        continue
                    yield Completion(
                        model_id,
                        start_position=-len(argument_prefix),
                        display_meta=provider,
                    )
                return

            if canonical_command == '/help':
                lowered_prefix = argument_prefix.lower()
                for name, description in _iter_command_completion_entries():
                    if name.startswith(lowered_prefix):
                        yield Completion(
                            name,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/diff':
                lowered_prefix = argument_prefix.lower()
                for option, description in (
                    ('--stat', 'Summary by file'),
                    ('--name-only', 'Changed file names'),
                    ('--patch', 'Full patch'),
                ):
                    if option.startswith(lowered_prefix):
                        yield Completion(
                            option,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/resume':
                lowered_prefix = argument_prefix.lower()
                seen: set[str] = set()
                for candidate, description in session_loader():
                    if candidate in seen:
                        continue
                    if lowered_prefix and not candidate.lower().startswith(
                        lowered_prefix
                    ):
                        continue
                    seen.add(candidate)
                    yield Completion(
                        candidate,
                        start_position=-len(argument_prefix),
                        display_meta=description,
                    )

    return SlashCommandCompleter()


# ---------------------------------------------------------------------------
# Key bindings for prompt_toolkit
# ---------------------------------------------------------------------------


def _build_bindings() -> Any:
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        """Alt+Enter inserts a newline (multi-line input)."""
        event.current_buffer.insert_text('\n')

    return kb


def _supports_prompt_session(input_stream: Any, output_stream: Any) -> bool:
    """Use prompt_toolkit only when both streams are attached to a TTY."""
    input_is_tty = bool(getattr(input_stream, 'isatty', lambda: False)())
    output_is_tty = bool(getattr(output_stream, 'isatty', lambda: False)())
    return input_is_tty and output_is_tty and _prompt_toolkit_available()


# ---------------------------------------------------------------------------
# REPL class
# ---------------------------------------------------------------------------


class Repl(SlashCommandsMixin, SessionLifecycleMixin, RunHelpersMixin):
    """Interactive REPL that drives an in-process agent session."""

    def __init__(self, config: AppConfig, console: Console) -> None:
        self._config = config
        self._console = console
        self._hud = HUDBar()
        self._reasoning = ReasoningDisplay()
        self._renderer: Any | None = None
        self._event_stream: EventStream | None = None
        self._controller: Any | None = None
        self._running = True
        # Bootstrap components (stored for session resume).
        self._agent: Any | None = None
        self._runtime: Any | None = None
        self._memory: Any | None = None
        self._llm_registry: Any | None = None
        self._conversation_stats: Any | None = None
        self._acquire_result: Any | None = None
        self._pending_resume: str | None = None
        self._next_action: Any | None = None
        self._last_user_message: str | None = None
        self._queued_input: list[str] = []
        #: Single-line bootstrap / idle status under the stats bar (prompt_toolkit only).
        self._footer_system_status: str = ''
        self._footer_system_kind: str = 'system'
        self._pt_session: Any | None = None
        #: Shown once per REPL run when Ctrl+C is pressed at the input prompt.
        self._prompt_ctrl_c_hint_shown: bool = False

    def _invalidate_pt(self) -> None:
        sess = self._pt_session
        if sess is None:
            return
        app = getattr(sess, 'app', None)
        if app is not None:
            app.invalidate()

    def _sync_terminal_after_agent_turn(self, session: Any | None) -> None:
        """Restore sane stdout/stderr after Rich Live so the next prompt can paint.

        While the agent runs, ``prompt_toolkit`` is idle (``app._is_running`` is
        false), so ``Application.invalidate()`` is a no-op. Rich may leave the
        cursor hidden or streams unsynced — without this, the multiline prompt
        sometimes never appears until the user resizes the terminal.
        """
        if session is None:
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        try:
            self._console.show_cursor(True)
        except Exception:
            pass
        out = getattr(session, 'output', None)
        if out is not None:
            try:
                # Leave the cursor on a fresh row after Rich scrollback so the
                # next full-screen prompt layout computes correctly.
                out.write('\n')
                out.flush()
            except Exception:
                pass

    def _set_footer_system_line(self, text: str, *, kind: str = 'system') -> None:
        """One shared status line under the stats bar; replaces previous text."""
        self._footer_system_status = text
        self._footer_system_kind = kind
        self._invalidate_pt()

    def _append_footer_system_fragments(
        self,
        fragments: list[tuple[str, str]],
        add: Callable[[str, str], None],
    ) -> None:
        status = self._footer_system_status.strip()
        if not status:
            return
        warn = self._footer_system_kind.strip().lower() == 'warning'
        body_cls = (
            'class:prompt.footer.warn_body' if warn else 'class:prompt.footer.body'
        )
        label = 'system'
        sep = ': '
        cols = shutil.get_terminal_size((110, 24)).columns
        reserve = 5 + len(label) + len(sep)
        max_w = max(16, cols - reserve)
        if len(status) > max_w:
            status = status[: max_w - 1] + '…'
        add('', '\n')
        if warn:
            add('class:prompt.footer.warn_bracket', '[')
            add('class:prompt.footer.warn_core', '!')
            add('class:prompt.footer.warn_bracket', ']  ')
            add('class:prompt.footer.warn_kicker', label)
            add('class:prompt.footer.warn_sep', sep)
        else:
            add('class:prompt.footer.badge_bracket', '[')
            add('class:prompt.footer.badge_core', 'i')
            add('class:prompt.footer.badge_bracket', ']  ')
            add('class:prompt.footer.kicker', label)
            add('class:prompt.footer.sep', sep)
        add(body_cls, status)

    @property
    def pending_resume(self) -> str | None:
        return self._pending_resume

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = renderer

    def set_controller(self, controller: Any) -> None:
        self._controller = controller

    def set_bootstrap_state(
        self,
        *,
        agent: Any | None = None,
        runtime: Any | None = None,
        memory: Any | None = None,
        llm_registry: Any | None = None,
        conversation_stats: Any | None = None,
        event_stream: Any | None = None,
        acquire_result: Any | None = None,
    ) -> None:
        if agent is not None:
            self._agent = agent
        if runtime is not None:
            self._runtime = runtime
        if memory is not None:
            self._memory = memory
        if llm_registry is not None:
            self._llm_registry = llm_registry
        if conversation_stats is not None:
            self._conversation_stats = conversation_stats
        if event_stream is not None:
            self._event_stream = event_stream
        if acquire_result is not None:
            self._acquire_result = acquire_result

    def queue_initial_input(self, text: str) -> None:
        if text:
            self._queued_input.append(text)

    def _current_prompt_state(self) -> AgentState | None:
        renderer = self._renderer
        state = (
            getattr(renderer, 'current_state', None) if renderer is not None else None
        )
        if isinstance(state, AgentState):
            return state

        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                candidate = controller.get_agent_state()
                if isinstance(candidate, AgentState):
                    return candidate
        return None

    def _prompt_message(self) -> str:
        state = self._current_prompt_state()
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            label = 'retry '
        else:
            label = ''
        return f'{label}❯ '

    def _prompt_placeholder(self) -> Any:
        from prompt_toolkit.formatted_text import HTML

        return HTML(
            '<style fg="#5d7286"><i>Describe the task, or type /help</i></style>'
        )

    def _prompt_state_label(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return 'Needs approval'
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return 'Needs attention'
        if state == AgentState.RUNNING:
            return 'Running'
        if state == AgentState.FINISHED:
            return 'Done'
        if state == AgentState.STOPPED:
            return 'Stopped'
        return 'Ready'

    def _prompt_autonomy_label(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                level = str(getattr(ac, 'autonomy_level', 'balanced')).strip().lower()
                if level in _AUTONOMY_LEVEL_HINTS:
                    return f'autonomy:{level}'
        return 'autonomy:balanced'

    def _prompt_panel_data(self) -> dict[str, str]:
        hud = self._hud.state
        provider, model = HUDBar.describe_model(hud.model)
        tokens = (
            HUDBar._format_tokens(hud.context_tokens) if hud.context_tokens > 0 else '0'
        )
        lim = HUDBar._format_tokens(hud.context_limit) if hud.context_limit else '?'
        if hud.context_tokens == 0 and hud.context_limit == 0:
            token_display = '0 tokens'
        elif hud.context_limit == 0:
            token_display = f'{tokens} tokens'
        else:
            token_display = f'{tokens}/{lim}'
        mcp_txt = HUDBar._format_mcp_servers_label(hud.mcp_servers)
        skills_txt = HUDBar._format_skills_label(self._hud.bundled_skill_count)
        return {
            'state_label': self._prompt_state_label(),
            'autonomy_label': self._prompt_autonomy_label(),
            'workspace': (hud.workspace_path or '').strip(),
            'provider': provider,
            'model': model,
            'token_display': token_display,
            'cost': f'${hud.cost_usd:.4f}',
            'calls': f'{hud.llm_calls} calls',
            'mcp': mcp_txt,
            'skills': skills_txt,
            'ledger': hud.ledger_status,
        }

    def _prompt_state_style(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return 'class:prompt.badge.review'
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return 'class:prompt.badge.error'
        if state == AgentState.RUNNING:
            return 'class:prompt.badge.running'
        return 'class:prompt.badge.ready'

    def _prompt_autonomy_style(self) -> str:
        label = self._prompt_autonomy_label()
        if 'full' in label:
            return 'class:prompt.autonomy.full'
        if 'supervised' in label:
            return 'class:prompt.autonomy.supervised'
        return 'class:prompt.autonomy.balanced'

    @staticmethod
    def _prompt_ledger_style(ledger_status: str) -> str:
        if ledger_status in {'Healthy', 'Ready', 'Idle', 'Starting'}:
            return 'class:prompt.health.good'
        if ledger_status in {'Review', 'Paused'}:
            return 'class:prompt.health.warn'
        return 'class:prompt.health.bad'

    def _prompt_toolbar_text(self) -> str:
        data = self._prompt_panel_data()
        state_label = data['state_label']
        autonomy_label = data['autonomy_label']
        controls = f'{state_label}  │  {autonomy_label}  │  Tab for commands'
        telemetry = (
            f'provider: {data["provider"]}  │  model: {data["model"]}  │  {data["token_display"]}  │  {data["cost"]}  │  '
            f'{data["calls"]}  │  {data["mcp"]}  │  {data["skills"]}  │  {data["ledger"]}'
        )
        return f' {controls}\n {telemetry} '

    def _prompt_stats_row1_fragments(
        self, data: dict[str, str], compact: bool
    ) -> list[tuple[str, str]]:
        frags: list[tuple[str, str]] = []
        frags.append(('class:prompt.brand', 'GRINTA'))
        frags.append(('class:prompt.dim', '  '))
        frags.append((self._prompt_state_style(), f' {data["state_label"].upper()} '))
        frags.append(('class:prompt.dim', '  '))
        frags.append((self._prompt_autonomy_style(), data['autonomy_label']))
        if not compact:
            frags.append(('class:prompt.dim', '  '))
            frags.append(('class:prompt.hint', 'Tab for commands'))
        return frags

    def _prompt_stats_row2_fragments(
        self, data: dict[str, str], compact: bool, width: int = 120
    ) -> list[tuple[str, str]]:
        """Build row-2 fragments, wrapping to a second line when content exceeds width."""
        sep = '  \u2022  '

        ws_raw = (data.get('workspace') or '').strip()
        # Required prefix: optional workspace, then provider + model + tokens + cost
        base: list[tuple[str, str]] = []
        if ws_raw:
            ws_max = max(18, min(72, width - 50))
            ws_show = HUDBar.ellipsize_path(ws_raw, ws_max)
            base.extend(
                [
                    ('class:prompt.dim', 'workspace:'),
                    ('class:prompt.sep', ' '),
                    ('class:prompt.model', ws_show),
                    ('class:prompt.sep', sep),
                ]
            )
        base.extend(
            [
                ('class:prompt.dim', 'provider:'),
                ('class:prompt.sep', ' '),
                ('class:prompt.model', data['provider']),
                ('class:prompt.sep', sep),
                ('class:prompt.dim', 'model:'),
                ('class:prompt.sep', ' '),
                ('class:prompt.model', data['model']),
                ('class:prompt.sep', sep),
                ('class:prompt.value', data['token_display']),
                ('class:prompt.sep', sep),
                ('class:prompt.value', data['cost']),
            ]
        )

        # Optional fields in priority order.
        optionals: list[tuple[str, str]] = [
            (self._prompt_ledger_style(data['ledger']), data['ledger']),
            ('class:prompt.value', data['calls']),
            ('class:prompt.value', data['mcp']),
            ('class:prompt.value', data['skills']),
        ]

        def _len(frags: list[tuple[str, str]]) -> int:
            return sum(len(t) for _, t in frags)

        # Build the full single-line version first.
        opt_frags: list[tuple[str, str]] = []
        for item_style, item_text in optionals:
            opt_frags.extend([('class:prompt.sep', sep), (item_style, item_text)])

        all_frags = list(base) + opt_frags
        if _len(all_frags) <= width:
            return all_frags

        # Overflow → wrap: required fields on line 1, optionals on line 2.
        result = list(base)
        result.append(('', '\n'))
        indent = ' ' * 10  # width of "provider: " to align the wrapped row
        result.append(('class:prompt.dim', indent))
        for idx, (item_style, item_text) in enumerate(optionals):
            if idx > 0:
                result.append(('class:prompt.sep', sep))
            result.append((item_style, item_text))

        return result

    def _prompt_bottom_toolbar(self) -> Any:
        """Two-line status under the input; no filled backgrounds (terminal default)."""
        width = shutil.get_terminal_size((110, 24)).columns
        data = self._prompt_panel_data()
        compact = width < 110

        # Keep HUD state/autonomy in sync so the Live-mode HUD matches.
        self._hud.update_agent_state(data['state_label'])
        level = data['autonomy_label'].replace('autonomy:', '')
        self._hud.update_autonomy(level)

        # Keep the compact line readable by folding provider/model into one token.
        model = (
            data['model']
            if data['provider'] in {'(not set)', '(unknown)'}
            else f'{data["provider"]}/{data["model"]}'
        )

        fragments: list[tuple[str, str]] = []

        def add(style: str, text: str) -> None:
            fragments.append((style, text))

        if width < 72:
            ws = (data.get('workspace') or '').strip()
            ws_prefix = f'{HUDBar.ellipsize_path(ws, 28)} · ' if ws else ''
            line = (
                f'{ws_prefix}{data["state_label"]} · {data["autonomy_label"]} · '
                f'{model} · {data["token_display"]} · {data["cost"]}'
            )
            add('class:prompt.dim', line)
            self._append_footer_system_fragments(fragments, add)
            return fragments

        add('class:prompt.dim', '\u2500' * width)
        add('', '\n')
        fragments.extend(self._prompt_stats_row1_fragments(data, compact))
        add('', '\n')
        # Pass actual terminal width so row 2 never overflows.
        fragments.extend(self._prompt_stats_row2_fragments(data, compact, width=width))
        self._append_footer_system_fragments(fragments, add)
        return fragments

    def _prompt_panel_message(self) -> Any:
        return [
            ('class:prompt.arrow', self._prompt_message()),
        ]

    def _create_prompt_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style

        from backend.cli.session_manager import get_session_suggestions

        prompt_style = Style.from_dict(
            {
                # Default prompt text; no bg so the terminal background shows through.
                '': 'noreverse #e6eef7',
                # PT defaults bottom-toolbar to reverse — disable without adding a fill color.
                'bottom-toolbar': 'noreverse',
                'bottom-toolbar.text': 'noreverse',
                'prompt.border': CLR_THINKING_BORDER,
                'prompt.frame.border': f'bold {CLR_STATUS_OK}',
                'prompt.brand': CLR_BRAND,
                'prompt.dim': CLR_META,
                'prompt.model': CLR_HUD_MODEL,
                'prompt.value': CLR_HUD_DETAIL,
                'prompt.sep': CLR_SEP,
                'prompt.arrow': CLR_BRAND,
                'prompt.hint': CLR_AUTONOMY_FULL,
                'prompt.badge.ready': f'bold {CLR_STATUS_OK}',
                'prompt.badge.running': CLR_STATE_RUNNING,
                'prompt.badge.review': f'bold {CLR_STATUS_WARN}',
                'prompt.badge.paused': f'bold {CLR_STATUS_WARN}',
                'prompt.badge.error': f'bold {CLR_STATUS_ERR}',
                'prompt.autonomy.balanced': CLR_AUTONOMY_BALANCED,
                'prompt.autonomy.full': CLR_AUTONOMY_FULL,
                'prompt.autonomy.supervised': CLR_AUTONOMY_SUPERVISED,
                'prompt.health.good': f'bold {CLR_STATUS_OK}',
                'prompt.health.warn': f'bold {CLR_STATUS_WARN}',
                'prompt.health.bad': f'bold {CLR_STATUS_ERR}',
                'prompt.footer.badge_bracket': '#0e7490',
                'prompt.footer.badge_core': 'bold #22d3ee',
                'prompt.footer.kicker': 'bold #a5f3fc',
                'prompt.footer.sep': CLR_META,
                'prompt.footer.body': CLR_MUTED_TEXT,
                'prompt.footer.warn_bracket': '#a16207',
                'prompt.footer.warn_core': 'bold #facc15',
                'prompt.footer.warn_kicker': 'bold #fde68a',
                'prompt.footer.warn_sep': '#92400e',
                'prompt.footer.warn_body': CLR_STATUS_WARN,
                'completion-menu': 'bg:#0d1f30 #b8c7d8',
                'completion-menu.completion': 'bg:#0d1f30 #b8c7d8',
                'completion-menu.completion.current': 'bg:#1e4976 bold #ffffff',
                'completion-menu.meta': 'bg:#0a1929 #5c7fa0',
                'completion-menu.meta.completion': 'bg:#0a1929 #5c7fa0',
                'completion-menu.meta.completion.current': 'bg:#163350 #93c5fd',
                'completion-menu.multi-column-meta': 'bg:#0a1929 #5c7fa0',
                'scrollbar.background': 'bg:#0d1f30',
                'scrollbar.button': 'bg:#1e4976',
            }
        )

        return PromptSession(
            message=self._prompt_panel_message,
            bottom_toolbar=self._prompt_bottom_toolbar,
            history=FileHistory(str(_ensure_history())),
            key_bindings=_build_bindings(),
            completer=_build_command_completer(
                lambda: get_session_suggestions(self._config)
            ),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            reserve_space_for_menu=8,
            enable_history_search=True,
            multiline=False,
            mouse_support=False,
            style=prompt_style,
            erase_when_done=True,
            placeholder=self._prompt_placeholder,
        )

    async def ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        memory: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        ensure_controller_loop = cast(Any, self._ensure_controller_loop)
        return await ensure_controller_loop(
            controller=controller,
            agent_task=agent_task,
            create_controller=create_controller,
            create_status_callback=create_status_callback,
            run_agent_until_done=run_agent_until_done,
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            memory=memory,
            end_states=end_states,
        )

    async def cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        await self._cancel_agent(agent_task)

    async def resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        resume_session = cast(Any, self._resume_session)
        return await resume_session(
            target,
            config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def handle_autonomy_command(self, text: str) -> None:
        try:
            parsed = _parse_slash_command(text)
        except SlashCommandParseError as exc:
            self._warn(str(exc))
            return
        self._handle_autonomy_command(parsed)

    def handle_command(self, text: str) -> bool:
        return self._handle_command(text)

    def _warn(self, message: str, *, title: str = 'warning') -> None:
        if self._renderer is not None:
            self._renderer.add_system_message(message, title=title)

    def _usage(self, command_name: str) -> str:
        spec = _find_command_spec(command_name)
        return spec.usage if spec is not None else command_name

    def _reject_extra_args(self, parsed: ParsedSlashCommand) -> bool:
        if not parsed.args:
            return False
        self._warn(f'Usage: {self._usage(parsed.name)}')
        return True

    def _command_project_root(self) -> Path:
        raw_project = getattr(self._config, 'project_root', None)
        if isinstance(raw_project, str) and raw_project.strip():
            with contextlib.suppress(OSError):
                return Path(raw_project).expanduser().resolve()
        return Path.cwd().resolve()

    async def _read_non_interactive_input(self) -> str:
        if self._queued_input:
            return self._queued_input.pop(0)
        self._console.print('>>> ', end='')
        return await asyncio.to_thread(sys.stdin.readline)

    # -- public entry point ------------------------------------------------

    async def run(self) -> None:
        """Boot the engine, subscribe to events, and loop on user input."""
        loop = asyncio.get_running_loop()
        agent_task: asyncio.Task | None = None
        bootstrap_task: asyncio.Task[None] | None = None

        # -- imports (always needed) ----------------------------------------
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.bootstrap.main import (
            _create_early_status_callback,
        )
        from backend.core.bootstrap.setup import create_controller

        try:
            bootstrap_task: asyncio.Task[None] | None = None  # type: ignore
            config = self._config
            self._hud.update_model(get_current_model(config))
            self._hud.update_workspace(getattr(config, 'project_root', None))

            # -- prompt session (fast, no I/O) --------------------------------
            session = self._build_prompt_session()

            # -- renderer (no event-stream subscription yet) ------------------
            renderer = self._build_renderer(session, loop)

            # -- staged init runs in background while user sees the prompt -----
            chat_ready_done = asyncio.Event()
            engine_init_done = asyncio.Event()
            engine_init_exc: list[BaseException | None] = [None]

            # -- enter input loop ---------------------------------------------
            controller = None
            bootstrap_task = None
            # RATE_LIMITED is intentionally omitted: the retry worker resumes the
            # agent after backoff; run_agent_until_done must keep running until a
            # true terminal state so controller.step() chains stay attached.
            end_states = [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
            ]

            self._hud.update_ledger('Starting')
            if session is not None:
                self._set_footer_system_line('Initializing engine...')
            else:
                renderer.add_system_message('Initializing engine...', title='system')
            bootstrap_task = asyncio.create_task(
                self._engine_bootstrap(
                    session, renderer, chat_ready_done,
                    engine_init_done, engine_init_exc,
                ),
                name='grinta-engine-bootstrap',
            )

            while self._running:
                stop = await self._repl_iteration(
                    session, controller, agent_task,
                    chat_ready_done, engine_init_done, engine_init_exc,
                    create_controller, _create_early_status_callback,
                    run_agent_until_done, end_states,
                )
                if stop is None:
                    break
                controller, agent_task = stop
        finally:
            await self._finalize_repl_run(bootstrap_task, agent_task)

    async def _repl_iteration(
        self,
        session: Any | None,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        chat_ready_done: asyncio.Event,
        engine_init_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None] | None:
        """Run one iteration of the REPL input loop. Returns None to break."""
        user_input = await self._read_repl_input(session)
        if user_input is None:
            return None
        if not user_input:
            return controller, agent_task
        text = user_input.strip()
        if not text or self._discard_terminal_noise(text):
            return controller, agent_task

        if text.startswith('/'):
            handled = await self._process_slash_command(
                text, agent_task, controller,
                engine_init_done, engine_init_exc,
                create_controller, create_status_callback,
                run_agent_until_done, end_states,
            )
            if handled is None:
                return None
            keep, controller, agent_task = handled
            if keep:
                return controller, agent_task
            # else fall through to dispatch (compact/retry)

        await chat_ready_done.wait()
        if engine_init_exc[0] is not None:
            return controller, agent_task

        if not self._validate_engine_components_ready():
            return None

        controller, agent_task = await self._dispatch_user_turn(
            text, controller, agent_task,
            create_controller, create_status_callback,
            run_agent_until_done, end_states, session,
        )
        return controller, agent_task

