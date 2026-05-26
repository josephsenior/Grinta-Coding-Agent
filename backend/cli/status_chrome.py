"""Shared status chrome for HUD bar, Rich Live fake prompt, and prompt_toolkit toolbar.

Single source of truth for breakpoints, token/cost formatting, and layout tiers so
idle vs agent-turn surfaces cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from backend.cli.hud import HUDBar
from backend.cli.theme import (
    CLR_AUTONOMY_BALANCED,
    CLR_AUTONOMY_CONSERVATIVE,
    CLR_AUTONOMY_FULL,
    CLR_BRAND,
    CLR_HUD_DETAIL,
    CLR_HUD_MODEL,
    CLR_META,
    CLR_SEP,
    CLR_STATE_RUNNING,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    STYLE_EMPTY,
    use_ascii_cli_symbols,
)

# Below this terminal width, toolbar and Live fake prompt use one dense status line.
STATUS_CHROME_COMPACT_WIDTH = 60

_UNKNOWN_PROVIDERS = frozenset({'(not set)', '(unknown)'})

_FAKE_PROMPT_BADGE_STYLES: dict[str, str] = {
    'Running': CLR_STATE_RUNNING,
    'Ready': CLR_STATUS_OK + ' bold',
    'Done': CLR_STATUS_OK + ' bold',
    'Finished': CLR_STATUS_OK + ' bold',
    'Needs approval': CLR_STATUS_WARN + ' bold',
    'Needs attention': CLR_STATUS_ERR + ' bold',
    'Stopped': CLR_STATUS_ERR + ' bold',
}
_FAKE_PROMPT_LEDGER_OK: frozenset[str] = frozenset(
    {'Healthy', 'Ready', 'Idle', 'Starting'}
)
_FAKE_PROMPT_LEDGER_WARN: frozenset[str] = frozenset({'Review', 'Paused'})
_FAKE_PROMPT_AUTONOMY_STYLES: dict[str, str] = {
    'full': CLR_AUTONOMY_FULL,
    'conservative': CLR_AUTONOMY_CONSERVATIVE,
}

SEP_ITEM: tuple[str, str] = (' · ', CLR_SEP)


def workspace_path_display_max(term_width: int) -> int:
    """Path ellipsis budget for compact status lines (tighter when *term_width* is small)."""
    w = int(term_width)
    if w < 48:
        return 10
    if w < STATUS_CHROME_COMPACT_WIDTH:
        return 16
    return 24


@dataclass(frozen=True)
class StatusFields:
    """Normalized snapshot for all status chrome surfaces."""

    provider: str
    model: str
    model_display: str
    token_display_compact: str
    cost_usd: float
    llm_calls: int
    mcp_short: str
    skills_short: str
    ledger_status: str
    agent_state_label: str
    autonomy_level: str
    workspace_path: str
    #: Number of context condensations in this session.
    condensation_count: int = 0
    #: Token usage percentage (0-100).
    token_usage_pct: int = 0


def status_fields_from_hud(hud: Any, bundled_skill_count: int) -> StatusFields:
    """Build fields from :class:`~backend.cli.hud.HUDState` and bundled skill count."""
    provider, model = HUDBar.describe_model(hud.model)
    model_display = f'{provider}/{model}' if provider and model else model

    total = HUDBar._format_tokens(int(getattr(hud, 'total_tokens', 0) or 0))
    ctx = HUDBar._format_tokens(hud.context_tokens)
    lim_tok = HUDBar._format_tokens(hud.context_limit) if hud.context_limit else None
    is_estimated = getattr(hud, 'token_usage_estimated', False)
    if (
        int(getattr(hud, 'total_tokens', 0) or 0) == 0
        and hud.context_tokens == 0
        and hud.context_limit == 0
    ):
        token_display_compact = '0'
    elif int(getattr(hud, 'total_tokens', 0) or 0) > 0 and hud.context_limit == 0:
        token_display_compact = f'{total}'
    elif int(getattr(hud, 'total_tokens', 0) or 0) > 0:
        context_detail = f'{ctx}/{lim_tok}' if lim_tok else ctx
        token_display_compact = f'{total} · {context_detail}'
    elif hud.context_limit == 0:
        token_display_compact = f'{ctx}'
    else:
        token_display_compact = f'{ctx}/{lim_tok}' if lim_tok else f'{ctx}'
    if is_estimated:
        token_display_compact += '~'  # ~ indicates estimated (not exact count)

    mcp_short = '?' if hud.mcp_servers is None else str(min(int(hud.mcp_servers), 99))
    skills_short = str(min(int(bundled_skill_count), 99))

    return StatusFields(
        provider=provider,
        model=model,
        model_display=model_display,
        token_display_compact=token_display_compact,
        cost_usd=float(hud.cost_usd),
        llm_calls=int(hud.llm_calls),
        mcp_short=mcp_short,
        skills_short=skills_short,
        ledger_status=str(hud.ledger_status),
        agent_state_label=str(hud.agent_state_label or 'Ready').strip(),
        autonomy_level=str(hud.autonomy_level or 'balanced').strip().lower(),
        workspace_path=_shorten_home(
            str(getattr(hud, 'workspace_path', '') or '').strip()
        ),
        condensation_count=int(getattr(hud, 'condensation_count', 0) or 0),
        token_usage_pct=(
            0
            if hud.context_limit == 0
            else min(100, max(0, hud.context_tokens * 100 // hud.context_limit))
        ),
    )


def autonomy_word_label(level: str) -> tuple[str, str]:
    """Return (label, Rich style) for the compact HUD bar autonomy segment."""
    raw = (level or 'balanced').strip().lower()
    if raw == 'full':
        return 'Autonomy: Full', CLR_AUTONOMY_FULL
    if raw == 'conservative':
        return 'Autonomy: Conservative', CLR_AUTONOMY_CONSERVATIVE
    return 'Autonomy: Balanced', CLR_AUTONOMY_BALANCED


def _shorten_home(path: str) -> str:
    """Replace the home directory prefix with ``~``."""
    if not path:
        return path
    home = str(Path.home())
    if path.lower().startswith(home.lower()):
        return '~' + path[len(home) :]
    return path


def autonomy_chrome_suffix(level: str) -> str:
    """``Autonomy: Balanced`` style string for GRINTA row / PT."""
    level_stripped = (level or 'balanced').strip()
    return f'Autonomy: {level_stripped.title()}'


def ledger_icon(ledger_status: str) -> str:
    if use_ascii_cli_symbols():
        mapping = {
            'Healthy': '*',
            'Ready': 'o',
            'Idle': 'o',
            'Starting': '.',
            'Review': '!',
            'Paused': '=',
            'Error': 'x',
        }
        return mapping.get(ledger_status, '?')
    mapping = {
        'Healthy': '●',
        'Ready': '○',
        'Idle': '○',
        'Starting': '◌',
        'Review': '◆',
        'Paused': '⏸',
        'Error': '✗',
    }
    return mapping.get(ledger_status, '?')


def ledger_rich_style(ledger_status: str) -> str:
    if ledger_status in {'Healthy', 'Ready', 'Idle', 'Starting'}:
        return f'{CLR_STATUS_OK} bold'
    if ledger_status == 'Review':
        return f'{CLR_STATUS_WARN} bold'
    if ledger_status == 'Paused':
        return CLR_STATUS_WARN
    return f'{CLR_STATUS_ERR} bold'


def ledger_fake_prompt_style(ledger_status: str) -> str:
    if ledger_status in _FAKE_PROMPT_LEDGER_WARN:
        return CLR_STATUS_WARN + ' bold'
    if ledger_status not in _FAKE_PROMPT_LEDGER_OK:
        return CLR_STATUS_ERR + ' bold'
    return CLR_STATUS_OK + ' bold'


def _token_bar(pct: int, width: int = 5) -> str:
    """Generate a compact token usage bar using thin characters.

    Uses thin blocks (▰) and light blocks (▱) for a minimal, instrumentation feel.
    At 100% shows a compact [OK] indicator instead of a full bar.

    Args:
        pct: Percentage (0-100)
        width: Number of bar characters

    Returns:
        Compact progress bar string like ▰▰▰▱▱ 65%
    """
    if pct <= 0:
        return f'[{"▱" * width}] 0%'
    if pct >= 100:
        return '[MAX]'
    filled = pct * width // 100
    empty = width - filled
    return f'[{"▰" * filled}{"▱" * empty}] {pct}%'


def _rich_compact_hud_minimal(fields: StatusFields) -> Text:
    """Minimal HUD line: just model, tokens, cost, state."""
    parts: list[tuple[str, str]] = []
    if fields.model_display and fields.model_display != '(not set)':
        parts.append((fields.model_display, CLR_HUD_MODEL))
        parts.append((' · ', CLR_SEP))
    parts.append(
        (
            f'{_token_bar(fields.token_usage_pct)} {fields.token_display_compact}',
            CLR_HUD_DETAIL,
        )
    )
    parts.append((' · ', CLR_SEP))
    if fields.cost_usd > 0:
        parts.append((f'${fields.cost_usd:.2f}', CLR_HUD_DETAIL))
        parts.append((' · ', CLR_SEP))
    parts.append((fields.agent_state_label, CLR_STATUS_OK))
    txt = Text()
    for content, style in parts:
        txt.append(content, style=style)
    return txt


def rich_compact_hud_line(
    fields: StatusFields,
    minimal: bool = False,
    *,
    term_width: int | None = None,
) -> Text:
    """Single-line Rich HUD: workspace, model, tokens, cost, calls, MCP, skills, state.

    Args:
        fields: StatusFields from HUD
        minimal: If True, strip decorations and show only essential info
        term_width: Terminal column count for path ellipsis (None → no truncation)
    """
    if minimal:
        # Minimal mode: just model, tokens, cost, state — cleaner than before
        return _rich_compact_hud_minimal(fields)

    # Full mode — grouped with subtle separators for a compact instrumentation feel
    auto_lbl, auto_style = autonomy_word_label(fields.autonomy_level)

    parts: list[tuple[str, str]] = []

    # Brand prefix
    parts.append(('GRINTA', CLR_BRAND))
    parts.append((' ', ''))

    if fields.workspace_path:
        ws_budget = workspace_path_display_max(term_width or 80)
        ws_display = HUDBar.ellipsize_path(fields.workspace_path, ws_budget)
        parts.append((ws_display, CLR_HUD_DETAIL))
        parts.append((' ', ''))

    # State
    parts.append(
        (f'[{fields.agent_state_label}]', ledger_rich_style(fields.ledger_status))
    )
    parts.append((' ', ''))
    parts.append((auto_lbl, auto_style))

    # Model
    parts.append((' · ', CLR_SEP))
    parts.append((fields.model_display, CLR_HUD_MODEL))

    # Tokens with compact bar
    parts.append((' · ', CLR_SEP))
    has_limit = '/' in fields.token_display_compact
    if has_limit:
        parts.append(
            (
                f'{_token_bar(fields.token_usage_pct)} {fields.token_display_compact}',
                CLR_HUD_DETAIL,
            )
        )
    else:
        parts.append((fields.token_display_compact, CLR_HUD_DETAIL))

    # Cost & calls — compact format
    parts.append((' · ', CLR_SEP))
    parts.append((f'${fields.cost_usd:.3f}', CLR_HUD_DETAIL))
    parts.append((f'{fields.llm_calls}c', CLR_HUD_DETAIL))

    # MCP & skills
    parts.append((' · ', CLR_SEP))
    parts.append((f'M:{fields.mcp_short}', CLR_HUD_DETAIL))
    parts.append((' ', ''))
    parts.append((f'S:{fields.skills_short}', CLR_HUD_DETAIL))

    if fields.condensation_count > 0:
        parts.append((' · ', CLR_SEP))
        parts.append((f'C:{fields.condensation_count}x', CLR_HUD_DETAIL))

    # Ledger state icon
    parts.append(('  ', ''))
    parts.append(
        (ledger_icon(fields.ledger_status), ledger_rich_style(fields.ledger_status))
    )

    txt = Text()
    for content, style in parts:
        txt.append(content, style=style)
    return txt


def rich_fake_prompt_row1(fields: StatusFields) -> Text:
    """GRINTA branded row with state badge and autonomy (matches PT row 1)."""
    state_label = fields.agent_state_label or 'Running'
    row1 = Text()
    row1.append('GRINTA', style=CLR_BRAND)
    row1.append('  ', style=STYLE_EMPTY)
    row1.append(
        f' {state_label.upper()} ',
        style=_FAKE_PROMPT_BADGE_STYLES.get(state_label, CLR_STATUS_OK + ' bold'),
    )
    row1.append('  ', style=STYLE_EMPTY)
    auto_style = CLR_AUTONOMY_BALANCED
    for needle, style in _FAKE_PROMPT_AUTONOMY_STYLES.items():
        if needle in fields.autonomy_level:
            auto_style = style
            break
    row1.append(autonomy_chrome_suffix(fields.autonomy_level), style=auto_style)
    return row1


def rich_fake_prompt_metrics_row(fields: StatusFields) -> Text:
    """Single stats row: model, tokens, cost, calls, MCP, skills, ledger text."""
    sep = SEP_ITEM
    ledger_style = ledger_fake_prompt_style(fields.ledger_status)
    has_limit = '/' in fields.token_display_compact
    token_display = (
        f'Tokens: {_token_bar(fields.token_usage_pct)} {fields.token_display_compact}'
        if has_limit
        else f'Tokens: {fields.token_display_compact}'
    )
    primary_parts: list[tuple[str, str]] = [
        (fields.model_display, CLR_HUD_MODEL),
        sep,
        (token_display, CLR_HUD_DETAIL),
        sep,
        (f'Cost: ${fields.cost_usd:.3f}', CLR_HUD_DETAIL),
        sep,
        (f'Calls: {fields.llm_calls}', CLR_HUD_DETAIL),
        sep,
        (f'MCP: {fields.mcp_short}', CLR_HUD_DETAIL),
        sep,
        (f'Skills: {fields.skills_short}', CLR_HUD_DETAIL),
    ]
    if fields.condensation_count > 0:
        primary_parts.append(sep)
        primary_parts.append(
            (f'Condensed: {fields.condensation_count}x', CLR_HUD_DETAIL)
        )

    primary_parts.append(sep)
    primary_parts.append((fields.ledger_status, ledger_style))
    row = Text()
    for content, style in primary_parts:
        row.append(content, style=style)
    return row


def rich_fake_prompt_input_row(fields: StatusFields) -> Any:
    """Spinner + subline above the rule (agent running vs idle)."""
    state_l = (fields.agent_state_label or 'Running').strip()
    if state_l.lower() == 'running':
        subline = 'Agent working · ctrl+c to interrupt'
        spin_style = CLR_BRAND
    else:
        subline = f'{state_l} · ctrl+c if needed'
        spin_style = f'dim {CLR_META}'
    text_style = f'italic {CLR_META}'
    input_row = Table.grid()
    input_row.add_column(width=3)
    input_row.add_column()
    input_row.add_row(
        Spinner('dots', style=spin_style),
        Text(subline, style=text_style),
    )
    return input_row


def rich_fake_prompt_compact_line(
    fields: StatusFields, *, term_width: int = 120
) -> Text:
    """One dense line for narrow terminals (matches PT compact toolbar)."""
    ws = fields.workspace_path
    path_budget = workspace_path_display_max(term_width)
    ws_prefix = f'{HUDBar.ellipsize_path(ws, path_budget)} · ' if ws else ''
    autonomy_display = autonomy_chrome_suffix(fields.autonomy_level)
    has_limit = '/' in fields.token_display_compact
    token_display = (
        f'{_token_bar(fields.token_usage_pct, 4)} {fields.token_display_compact}'
        if has_limit and fields.token_usage_pct > 0
        else fields.token_display_compact
    )
    line = (
        f'{ws_prefix}{fields.agent_state_label} · {autonomy_display} · '
        f'{fields.model_display} · {token_display} · '
        f'${fields.cost_usd:.3f}'
    )
    return Text(line, style=CLR_META)


def rich_fake_prompt_group(fields: StatusFields, width: int) -> Group:
    """Full fake prompt body for Live mode at *width* columns."""
    if width < STATUS_CHROME_COMPACT_WIDTH:
        return Group(rich_fake_prompt_compact_line(fields, term_width=width))
    items: list[Any] = [
        rich_fake_prompt_input_row(fields),
        Text('─' * width, style=f'dim {CLR_SEP}'),
        rich_fake_prompt_row1(fields),
        rich_fake_prompt_metrics_row(fields),
    ]
    return Group(*items)


def pt_compact_line_plain(fields: StatusFields, *, term_width: int = 120) -> str:
    """Plain string for prompt_toolkit compact toolbar (single styled line)."""
    ws = fields.workspace_path
    path_budget = workspace_path_display_max(term_width)
    ws_prefix = f'{HUDBar.ellipsize_path(ws, path_budget)} · ' if ws else ''
    autonomy_display = autonomy_chrome_suffix(fields.autonomy_level)
    has_limit = '/' in fields.token_display_compact
    token_display = (
        f'{_token_bar(fields.token_usage_pct, 4)} {fields.token_display_compact}'
        if has_limit and fields.token_usage_pct > 0
        else fields.token_display_compact
    )
    return (
        f'{ws_prefix}{fields.agent_state_label} · {autonomy_display} · '
        f'{fields.model_display} · {token_display} · '
        f'${fields.cost_usd:.3f}'
    )


def pt_stats_row1_fragments(
    fields: StatusFields,
    state_style: str,
    autonomy_style: str,
) -> list[tuple[str, str]]:
    """GRINTA row fragments (prompt_toolkit style classes)."""
    autonomy_display = autonomy_chrome_suffix(fields.autonomy_level)
    return [
        ('class:prompt.brand', 'GRINTA'),
        ('class:prompt.dim', '  '),
        (state_style, f' {fields.agent_state_label.upper()} '),
        ('class:prompt.dim', '  '),
        (autonomy_style, autonomy_display),
    ]


def pt_stats_row2_fragments(
    fields: StatusFields,
    width: int,
    *,
    ledger_style: str,
    sep: str = '  •  ',
) -> list[tuple[str, str]]:
    """Telemetry row with optional wrap (matches previous Repl behavior)."""
    ws_raw = fields.workspace_path
    base: list[tuple[str, str]] = []
    if ws_raw:
        ws_max = max(16, min(64, width - 50))
        ws_show = HUDBar.ellipsize_path(ws_raw, ws_max)
        base.extend(
            [
                ('class:prompt.dim', 'ws:'),
                ('class:prompt.sep', ' '),
                ('class:prompt.model', ws_show),
                ('class:prompt.sep', sep),
            ]
        )
    base.extend(
        [
            ('class:prompt.dim', 'provider:'),
            ('class:prompt.sep', ' '),
            ('class:prompt.model', fields.provider),
            ('class:prompt.sep', sep),
            ('class:prompt.dim', 'model:'),
            ('class:prompt.sep', ' '),
            ('class:prompt.model', fields.model),
            ('class:prompt.sep', sep),
            (
                'class:prompt.value',
                (
                    f'Tokens: {_token_bar(fields.token_usage_pct)} {fields.token_display_compact}'
                    if '/' in fields.token_display_compact
                    else f'Tokens: {fields.token_display_compact}'
                ),
            ),
            ('class:prompt.sep', sep),
            ('class:prompt.value', f'Cost: ${fields.cost_usd:.3f}'),
        ]
    )

    optionals: list[tuple[str, str]] = [
        (ledger_style, fields.ledger_status),
        ('class:prompt.value', f'{fields.llm_calls} calls'),
    ]

    def _len(frags: list[tuple[str, str]]) -> int:
        return sum(len(t) for _, t in frags)

    opt_frags: list[tuple[str, str]] = []
    for item_style, item_text in optionals:
        opt_frags.extend([('class:prompt.sep', sep), (item_style, item_text)])

    all_frags = list(base) + opt_frags
    if _len(all_frags) <= width:
        return all_frags

    # Overflow → wrap: required fields on line 1, ledger + calls on line 2.
    result = list(base)
    result.append(('', '\n'))
    result.append(('class:prompt.dim', ' ' * 10))
    for idx, (item_style, item_text) in enumerate(optionals):
        if idx > 0:
            result.append(('class:prompt.sep', sep))
        result.append((item_style, item_text))
    return result
