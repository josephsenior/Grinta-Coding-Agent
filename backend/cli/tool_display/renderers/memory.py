"""Memory/context manager renderer."""

from __future__ import annotations

from typing import Any

from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_SECONDARY,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
)
from backend.cli.display.transcript import format_activity_primary


def render_memory_update(
    action: str,
    tokens_used: int = 0,
    context_limit: int = 0,
    entries_added: int = 0,
    entries_removed: int = 0,
    compression_ratio: float = 0.0,
) -> list[Any]:
    """Render memory/context update."""
    lines: list[Any] = []

    action_verb = action.replace('_', ' ').title()
    lines.append(format_activity_primary(action_verb, 'Memory'))

    if tokens_used and context_limit:
        pct = int((tokens_used / context_limit) * 100)
        bar = '█' * min(pct // 5, 20) + '░' * max(0, 20 - pct // 5)
        usage_str = f'[{CLR_BRAND_HUE if pct < 80 else CLR_STATUS_WARN}]{tokens_used:,}[/{CLR_BRAND_HUE if pct < 80 else CLR_STATUS_WARN}] / {context_limit:,} tokens'
        # Make memory section less prominent with dim styling
        lines.append(f'  [dim]Context  {usage_str}  {bar} {pct}%[/dim]')

    if entries_added or entries_removed:
        parts = []
        if entries_added:
            parts.append(f'[{CLR_STATUS_OK}]+{entries_added}[/{CLR_STATUS_OK}]')
        if entries_removed:
            parts.append(f'[{CLR_SECONDARY}]-{entries_removed}[/{CLR_SECONDARY}]')
        lines.append('  [dim]' + '  '.join(parts) + '[/dim]')

    if compression_ratio > 0:
        lines.append(f'  [dim]Compression: {compression_ratio:.1f}× ratio[/dim]')

    return lines
