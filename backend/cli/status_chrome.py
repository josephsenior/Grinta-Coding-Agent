"""Shared status chrome for HUD bar, Rich Live fake prompt, and prompt_toolkit toolbar.

Single source of truth for breakpoints, token/cost formatting, and layout tiers so
idle vs agent-turn surfaces cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
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
STATUS_CHROME_COMPACT_WIDTH = 72

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
        return 12
    if w < STATUS_CHROME_COMPACT_WIDTH:
        return 18
    return 28


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


def status_fields_from_hud(hud: Any, bundled_skill_count: int) -> StatusFields:
    """Build fields from :class:`~backend.cli.hud.HUDState` and bundled skill count."""
    provider, model = HUDBar.describe_model(hud.model)
    if provider in _UNKNOWN_PROVIDERS:
        model_display = model
    else:
        model_display = f'{provider}/{model}'

    ctx = HUDBar._format_tokens(hud.context_tokens)
    lim_tok = (
        HUDBar._format_tokens(hud.context_limit) if hud.context_limit else None
    )
    if hud.context_tokens == 0 and hud.context_limit == 0:
        token_display_compact = '0t'
    elif hud.context_limit == 0:
        token_display_compact = f'{ctx}t'
    else:
        token_display_compact = f'{ctx}/{lim_tok}' if lim_tok else f'{ctx}t'
    if getattr(hud, 'token_usage_estimated', False):
        token_display_compact += '~'

    mcp_short = (
        '?' if hud.mcp_servers is None else str(min(int(hud.mcp_servers), 99))
    )
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
        workspace_path=str(getattr(hud, 'workspace_path', '') or '').strip(),
    )


def autonomy_word_label(level: str) -> tuple[str, str]:
    """Return (short label, Rich style) for the compact HUD bar autonomy segment."""
    raw = (level or 'balanced').strip().lower()
    if raw == 'full':
        return 'Full', CLR_AUTONOMY_FULL
    if raw == 'conservative':
        return 'Conservative', CLR_AUTONOMY_CONSERVATIVE
    return 'Balanced', CLR_AUTONOMY_BALANCED


def autonomy_chrome_suffix(level: str) -> str:
    """``autonomy:balanced`` style string for GRINTA row / PT."""
    return f'autonomy:{(level or "balanced").strip().lower()}'


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


def rich_compact_hud_line(fields: StatusFields) -> Text:
    """Single-line Rich HUD: autonomy word, model, tokens, cost, calls, MCP, skills, icon."""
    auto_lbl, auto_style = autonomy_word_label(fields.autonomy_level)
    group_sep = ('  │  ', CLR_SEP)
    item_sep = (' · ', CLR_SEP)

    parts: list[tuple[str, str]] = [
        (' ', ''),
        (auto_lbl, auto_style),
        (' ', ''),
        (fields.model_display, CLR_HUD_MODEL),
        item_sep,
        (fields.token_display_compact, CLR_HUD_DETAIL),
        group_sep,
        (f'Cost: ${fields.cost_usd:.3f}', CLR_HUD_DETAIL),
        item_sep,
        (f'Calls: {fields.llm_calls}', CLR_HUD_DETAIL),
        group_sep,
        (f'MCP: {fields.mcp_short}', CLR_HUD_DETAIL),
        item_sep,
        (f'Skills: {fields.skills_short}', CLR_HUD_DETAIL),
        group_sep,
        (ledger_icon(fields.ledger_status), ledger_rich_style(fields.ledger_status)),
    ]
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
    primary_parts: list[tuple[str, str]] = [
        (fields.model_display, CLR_HUD_MODEL),
        sep,
        (f'Tokens: {fields.token_display_compact}', CLR_HUD_DETAIL),
        sep,
        (f'Cost: ${fields.cost_usd:.3f}', CLR_HUD_DETAIL),
        sep,
        (f'Calls: {fields.llm_calls}', CLR_HUD_DETAIL),
        sep,
        (f'MCP: {fields.mcp_short}', CLR_HUD_DETAIL),
        sep,
        (f'Skills: {fields.skills_short}', CLR_HUD_DETAIL),
        sep,
        (fields.ledger_status, ledger_style),
    ]
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
        subline = f'{state_l} · ctrl+c if you need to interrupt'
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
    line = (
        f'{ws_prefix}{fields.agent_state_label} · {autonomy_display} · '
        f'{fields.model_display} · {fields.token_display_compact} · '
        f'${fields.cost_usd:.3f}'
    )
    return Text(line, style=CLR_META)


def rich_fake_prompt_group(fields: StatusFields, width: int) -> Group:
    """Full fake prompt body for Live mode at *width* columns."""
    if width < STATUS_CHROME_COMPACT_WIDTH:
        return Group(rich_fake_prompt_compact_line(fields, term_width=width))
    items: list[Any] = [
        rich_fake_prompt_input_row(fields),
        Text('─' * width, style=CLR_SEP),
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
    return (
        f'{ws_prefix}{fields.agent_state_label} · {autonomy_display} · '
        f'{fields.model_display} · {fields.token_display_compact} · '
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
    sep: str = '  \u2022  ',
) -> list[tuple[str, str]]:
    """Telemetry row with optional wrap (matches previous Repl behavior).

    MCP/skills stay on HUD / Live chrome; the prompt toolbar stays compact with
    ledger + calls only after provider/model/tokens/cost (see Repl comment).
    """
    ws_raw = fields.workspace_path
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
            ('class:prompt.model', fields.provider),
            ('class:prompt.sep', sep),
            ('class:prompt.dim', 'model:'),
            ('class:prompt.sep', ' '),
            ('class:prompt.model', fields.model),
            ('class:prompt.sep', sep),
            ('class:prompt.value', f'Tokens: {fields.token_display_compact}'),
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
