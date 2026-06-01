"""Slash-command registry, parsing, help, and prompt-toolkit helpers for the REPL.

Pure code motion from :mod:`backend.cli.repl` (PR-1 of the file-size
decomposition). The bytes of logic are identical to the originals; only
their physical location has changed. The original :mod:`backend.cli.repl`
module now keeps a thin PEP 562 deprecation shim that re-exports these
names for one minor release, then drops them.

Nothing in this file is new — every function, constant, and class below
lived in ``backend/cli/repl.py`` before this split. See
``docs/internals/import-manifest.json`` for the module graph this module
belongs to.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Callable

from rich.table import Table

from backend.core.os_capabilities import OS_CAPS

logger = logging.getLogger(__name__)


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
    'conservative': 'Always ask before actions',
    'balanced': 'Ask only for high-risk actions',
    'full': 'Run without confirmation prompts',
}
_PLAYBOOK_SLASH_COMMANDS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec(
        '/add_repo_inst',
        'Scaffold repository playbook instructions',
        '/add_repo_inst',
        help_section='control',
    ),
    SlashCommandSpec(
        '/address_pr_comments',
        'Apply a PR-comment resolution workflow',
        '/address_pr_comments',
        help_section='control',
    ),
    SlashCommandSpec(
        '/api',
        'Use API implementation guidance',
        '/api',
        help_section='control',
    ),
    SlashCommandSpec(
        '/audit',
        'Run an audit-oriented review workflow',
        '/audit',
        help_section='control',
    ),
    SlashCommandSpec(
        '/ci',
        'Use CI triage and stabilization workflow',
        '/ci',
        help_section='control',
    ),
    SlashCommandSpec(
        '/codereview',
        'Apply pragmatic code-review checklist',
        '/codereview',
        help_section='control',
    ),
    SlashCommandSpec(
        '/codereview-roasted',
        'Apply strict code-review checklist',
        '/codereview-roasted',
        help_section='control',
    ),
    SlashCommandSpec(
        '/compress',
        'Use context compression workflow',
        '/compress',
        help_section='control',
    ),
    SlashCommandSpec(
        '/database',
        'Use database and schema guidance',
        '/database',
        help_section='control',
    ),
    SlashCommandSpec(
        '/debug',
        'Use systematic debugging workflow',
        '/debug',
        help_section='control',
    ),
    SlashCommandSpec(
        '/docs',
        'Use documentation authoring guidance',
        '/docs',
        help_section='control',
    ),
    SlashCommandSpec(
        '/feature',
        'Use structured feature delivery workflow',
        '/feature',
        help_section='control',
    ),
    SlashCommandSpec(
        '/hardened',
        'Use hardened execution workflow',
        '/hardened',
        help_section='control',
    ),
    SlashCommandSpec(
        '/orch-debug',
        'Debug orchestration-level issues',
        '/orch-debug',
        help_section='control',
    ),
    SlashCommandSpec(
        '/owasp',
        'Use OWASP-oriented security review guidance',
        '/owasp',
        help_section='control',
    ),
    SlashCommandSpec(
        '/perf',
        'Use performance and cost optimization workflow',
        '/perf',
        help_section='control',
    ),
    SlashCommandSpec(
        '/react',
        'Use React implementation guidance',
        '/react',
        help_section='control',
    ),
    SlashCommandSpec(
        '/recover',
        'Recover from failed or stuck runs',
        '/recover',
        help_section='control',
    ),
    SlashCommandSpec(
        '/refactor',
        'Use refactoring workflow guidance',
        '/refactor',
        help_section='control',
    ),
    SlashCommandSpec(
        '/release',
        'Use release readiness and rollout workflow',
        '/release',
        help_section='control',
    ),
    SlashCommandSpec(
        '/remember',
        'Capture durable lessons and memory signals',
        '/remember',
        help_section='control',
    ),
    SlashCommandSpec(
        '/security',
        'Use security hardening guidance',
        '/security',
        help_section='control',
    ),
    SlashCommandSpec(
        '/testing',
        'Use test planning and authoring workflow',
        '/testing',
        help_section='control',
    ),
    SlashCommandSpec(
        '/tool',
        'Use tool and MCP authoring workflow',
        '/tool',
        help_section='control',
    ),
    SlashCommandSpec(
        '/update_pr_description',
        'Refresh PR summary and test plan',
        '/update_pr_description',
        help_section='control',
    ),
    SlashCommandSpec(
        '/update_test',
        'Regenerate tests after implementation changes',
        '/update_test',
        help_section='control',
    ),
)
_SLASH_COMMANDS = (
    SlashCommandSpec(
        '/help',
        'Show commands and shortcuts',
        '/help [command|--all]',
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
        'View or set autonomy (conservative/balanced/full)',
        '/autonomy [conservative|balanced|full]',
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
        '/health',
        'Run a fast self-check (debugpy, ripgrep, git, model)',
        '/health',
        help_section='control',
    ),
    SlashCommandSpec(
        '/diff',
        'Show workspace git changes',
        '/diff [--stat|--name-only|--patch] [path]',
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
        '/search',
        'Search the session transcript for matching text',
        '/search <query>',
        help_section='control',
    ),
    SlashCommandSpec(
        '/clear', 'Clear the visible transcript', '/clear', help_section='control'
    ),
    SlashCommandSpec(
        '/exit', 'Quit grinta', '/exit', aliases=('/quit',), help_section='system'
    ),
    *_PLAYBOOK_SLASH_COMMANDS,
)

# Known models surfaced in `/model` tab-completion.
# provider/model pairs — provider shown as display_meta in the completer.
_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ('openai/gpt-4.1', 'OpenAI'),
    ('openai/gpt-4o', 'OpenAI'),
    ('openai/gpt-5.5', 'OpenAI'),
    ('anthropic/claude-opus-4-20250514', 'Anthropic'),
    ('anthropic/claude-sonnet-4-6', 'Anthropic'),
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


# Sections with more than this many commands are collapsed by default in `/help`.
_HELP_SECTION_COLLAPSE_THRESHOLD = 10

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
                '\n\nDid you mean '
                + ' or '.join(f'`{item}`' for item in suggestions)
                + '?'
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
    lines: list[str] = ['| Command | Purpose |', '| --- | --- |']
    for spec in specs:
        alias_text = (
            '; aliases: ' + ', '.join(f'`{alias}`' for alias in spec.aliases)
            if spec.aliases
            else ''
        )
        usage = spec.usage.replace('|', r'\|')
        lines.append(f'| `{usage}` | {spec.description}{alias_text} |')
    return lines


_HELP_INPUT_TIPS: tuple[str, ...] = (
    '',
    '**Input shortcuts**',
    '',
    '- `Tab` — autocomplete slash commands and arguments',
    '- `↑` / `↓` — search prompt history',
    '- `Alt+Enter` — insert a newline (multi-line input)',
    '- `Ctrl+C` — interrupt a running agent turn',
    '- `Ctrl+D` — close piped or terminal input',
    '- `/help <command>` — detailed help for a single command',
)


def _build_help_markdown(command_name: str | None = None) -> str:
    """Build the slash-command help block from the shared command registry."""
    from collections import defaultdict

    if command_name:
        return _help_for_specific_command(command_name)

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    lines: list[str] = [
        'Send plain-language tasks at the prompt. Slash commands are for session control, inspection, and settings.',
        '',
    ]
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


def _build_help_table(
    search_term: str | None = None, *, show_all: bool = False
) -> Table:
    """Build a Rich table of slash commands, optionally filtered by search term.

    Parameters
    ----------
    search_term:
        Fuzzy filter on command name/description.
    show_all:
        If True, expand all sections. If False, sections with more than
        ``_HELP_SECTION_COLLAPSE_THRESHOLD`` commands are collapsed.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return _build_help_table_fallback(search_term, show_all=show_all)

    from collections import defaultdict

    from backend.cli.theme import CLR_CARD_BORDER, CLR_CARD_TITLE, STYLE_DIM

    table = Table(
        title='Slash Commands',
        title_style=CLR_CARD_TITLE,
        border_style=CLR_CARD_BORDER,
        box=None,
        padding=(0, 1),
    )
    table.add_column('Command', style='bold cyan', no_wrap=True)
    table.add_column('Description', style=STYLE_DIM)

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    if search_term:
        search_lower = search_term.lower()
        filtered_sections: dict[str, list[SlashCommandSpec]] = {}
        for section, specs in by_section.items():
            matched = []
            for spec in specs:
                score = max(
                    fuzz.partial_ratio(search_lower, spec.name.lower()),
                    fuzz.partial_ratio(search_lower, spec.description.lower()),
                    fuzz.partial_ratio(search_lower, spec.usage.lower()),
                )
                if score > 60:
                    matched.append(spec)
            if matched:
                filtered_sections[section] = matched
        by_section = filtered_sections

    for section_key, title in _HELP_SECTIONS_ORDER:
        specs_list = by_section.get(section_key)
        if not specs_list:
            continue
        table.add_row('', '')
        count = len(specs_list)
        collapsed = (
            not show_all
            and count > _HELP_SECTION_COLLAPSE_THRESHOLD
            and not search_term
        )
        if collapsed:
            table.add_row(
                f'[bold]{title}[/bold]  [dim]({count} commands — use /help --all to expand)[/dim]',
                '',
            )
        else:
            table.add_row(f'[bold]{title}[/bold]  [dim]({count})[/dim]', '')
            for spec in specs_list:
                table.add_row(spec.usage, spec.description)

    return table


def _build_help_table_fallback(
    search_term: str | None = None, *, show_all: bool = False
) -> Table:
    """Fallback help table without fuzzy matching."""
    from collections import defaultdict

    from backend.cli.theme import CLR_CARD_BORDER, CLR_CARD_TITLE, STYLE_DIM

    table = Table(
        title='Slash Commands',
        title_style=CLR_CARD_TITLE,
        border_style=CLR_CARD_BORDER,
        box=None,
        padding=(0, 1),
    )
    table.add_column('Command', style='bold cyan', no_wrap=True)
    table.add_column('Description', style=STYLE_DIM)

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    if search_term:
        search_lower = search_term.lower()
        filtered_sections = {}
        for section, specs in by_section.items():
            matched = [
                spec
                for spec in specs
                if search_lower in spec.name.lower()
                or search_lower in spec.description.lower()
            ]
            if matched:
                filtered_sections[section] = matched
        by_section = filtered_sections

    for section_key, title in _HELP_SECTIONS_ORDER:
        specs_list = by_section.get(section_key)
        if not specs_list:
            continue
        table.add_row('', '')
        count = len(specs_list)
        collapsed = (
            not show_all
            and count > _HELP_SECTION_COLLAPSE_THRESHOLD
            and not search_term
        )
        if collapsed:
            table.add_row(
                f'[bold]{title}[/bold]  [dim]({count} commands — use /help --all to expand)[/dim]',
                '',
            )
        else:
            table.add_row(f'[bold]{title}[/bold]  [dim]({count})[/dim]', '')
            for spec in specs_list:
                table.add_row(spec.usage, spec.description)

    return table


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

    @kb.add(Keys.ControlR, eager=True)
    def _transcript_search(event):
        """Ctrl+R opens a transcript search prompt."""
        from prompt_toolkit.shortcuts import input_dialog
        from prompt_toolkit.styles import Style

        app = event.app

        async def _do_search():
            try:
                result = await input_dialog(
                    title='Search Transcript',
                    text='Enter search query:',
                    style=Style.from_dict(
                        {
                            'dialog': 'bg:#1b233a',
                            'dialog.body': 'bg:#0f1525 #e9e9e9',
                            'dialog.title': 'bg:#0f1525 #91abec bold',
                            'dialog.body text-area': 'bg:#0a0e1b #e9e9e9',
                        }
                    ),
                ).run_async()
                if result and result.strip():
                    # Insert the search command into the buffer
                    app.current_buffer.text = f'/search {result.strip()}'
                    app.current_buffer.validate_and_handle()
            except Exception:
                pass

        app.create_background_task(_do_search())

    return kb


def _supports_prompt_session(input_stream: Any, output_stream: Any) -> bool:
    """Use prompt_toolkit only when both streams are attached to a TTY."""
    input_is_tty = bool(getattr(input_stream, 'isatty', lambda: False)())
    output_is_tty = bool(getattr(output_stream, 'isatty', lambda: False)())
    return input_is_tty and output_is_tty and _prompt_toolkit_available()
