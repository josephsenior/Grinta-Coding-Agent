"""Help-system rendering for the slash-command registry.

Exposes three view shapes:
* ``build_help_markdown`` — grouped, by-section markdown block;
* ``build_help_table`` — Rich table with fuzzy search and section
  collapsing (``rapidfuzz``-based);
* ``build_help_table_fallback`` — substring-only fallback when
  ``rapidfuzz`` is unavailable.
"""

from __future__ import annotations

from difflib import get_close_matches

from rich.table import Table

from backend.cli._repl._slash_registry_commands import _COMMAND_NAMES, _SLASH_COMMANDS
from backend.cli._repl._slash_registry_models import SlashCommandSpec
from backend.cli._repl._slash_registry_parsing import canonical_command_name

# Sections with more than this many commands are collapsed by default in `/help`.
HELP_SECTION_COLLAPSE_THRESHOLD = 10

HELP_SECTIONS_ORDER: tuple[tuple[str, str], ...] = (
    ('session', 'Session & history'),
    ('model', 'Model & configuration'),
    ('control', 'Context & control'),
    ('system', 'System'),
)

HELP_INPUT_TIPS: tuple[str, ...] = (
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


def find_command_spec(command_name: str) -> SlashCommandSpec | None:
    normalized = command_name.strip().lower()
    if normalized and not normalized.startswith('/'):
        normalized = f'/{normalized}'
    canonical = canonical_command_name(normalized)
    for spec in _SLASH_COMMANDS:
        if spec.name == canonical:
            return spec
    return None


def help_for_specific_command(command_name: str) -> str:
    spec = find_command_spec(command_name)
    if spec is None:
        suggestions = closest_command_names(command_name)
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


def help_section_lines(specs: list[SlashCommandSpec]) -> list[str]:
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


def build_help_markdown(command_name: str | None = None) -> str:
    """Build the slash-command help block from the shared command registry."""
    from collections import defaultdict

    if command_name:
        return help_for_specific_command(command_name)

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    lines: list[str] = [
        'Send plain-language tasks at the prompt. Slash commands are for session control, inspection, and settings.',
        '',
    ]
    first_section = True
    for section_key, title in HELP_SECTIONS_ORDER:
        specs = by_section.get(section_key)
        if not specs:
            continue
        if not first_section:
            lines.append('')
        first_section = False
        lines.append(f'**{title}**')
        lines.append('')
        lines.extend(help_section_lines(specs))

    lines.extend(HELP_INPUT_TIPS)
    return '\n'.join(lines)


def build_help_table(
    search_term: str | None = None, *, show_all: bool = False
) -> Table:
    """Build a Rich table of slash commands, optionally filtered by search term.

    Parameters
    ----------
    search_term:
        Fuzzy filter on command name/description.
    show_all:
        If True, expand all sections. If False, sections with more than
        ``HELP_SECTION_COLLAPSE_THRESHOLD`` commands are collapsed.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return build_help_table_fallback(search_term, show_all=show_all)

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

    for section_key, title in HELP_SECTIONS_ORDER:
        specs_list = by_section.get(section_key)
        if not specs_list:
            continue
        table.add_row('', '')
        count = len(specs_list)
        collapsed = (
            not show_all
            and count > HELP_SECTION_COLLAPSE_THRESHOLD
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


def build_help_table_fallback(
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

    for section_key, title in HELP_SECTIONS_ORDER:
        specs_list = by_section.get(section_key)
        if not specs_list:
            continue
        table.add_row('', '')
        count = len(specs_list)
        collapsed = (
            not show_all
            and count > HELP_SECTION_COLLAPSE_THRESHOLD
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


def closest_command_names(command: str, *, limit: int = 2) -> list[str]:
    """Suggest the closest matching slash commands for typos."""
    matches = get_close_matches(command, _COMMAND_NAMES, n=limit, cutoff=0.5)
    suggestions: list[str] = []
    for match in matches:
        if match not in suggestions:
            suggestions.append(match)
    return suggestions
