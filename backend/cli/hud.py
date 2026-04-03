"""Persistent footer status bar — the HUD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text


@dataclass
class HUDState:
    """Mutable state backing the HUD bar."""

    model: str = '(not set)'
    context_tokens: int = 0
    context_limit: int = 0
    cost_usd: float = 0.0
    ledger_status: str = 'Healthy'
    llm_calls: int = 0


class HUDBar:
    """Renderable footer bar: [Model] | [Context] | [Cost] | [Ledger]."""

    def __init__(self) -> None:
        self.state = HUDState()

    # -- rich renderable protocol ------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = options.max_width
        bar = self._format()
        pad = max(0, width - len(bar.plain))
        line = Text(' ') + bar + Text(' ' * pad)
        line.stylize('on grey15')
        yield line

    def _format(self) -> Text:
        ctx = self._format_tokens(self.state.context_tokens)
        lim = (
            self._format_tokens(self.state.context_limit)
            if self.state.context_limit
            else '?'
        )
        # Show a clean placeholder before the first LLM call.
        if self.state.context_tokens == 0 and self.state.context_limit == 0:
            token_display = '—'
        else:
            token_display = f'{ctx}/{lim}'
        parts = [
            (self.state.model, 'cyan'),
            (' │ ', 'dim'),
            (token_display, 'yellow'),
            (' │ ', 'dim'),
            (f'${self.state.cost_usd:.4f}', 'green'),
            (' │ ', 'dim'),
            (f'{self.state.llm_calls} calls', 'blue'),
            (' │ ', 'dim'),
            (self.state.ledger_status, self._ledger_style()),
        ]
        txt = Text()
        for content, style in parts:
            txt.append(content, style=style)
        return txt

    def _ledger_style(self) -> str:
        if self.state.ledger_status == 'Healthy':
            return 'green'
        if self.state.ledger_status == 'Idle':
            return 'yellow'
        return 'red bold'

    @staticmethod
    def _format_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f'{n / 1_000_000:.1f}M'
        if n >= 1_000:
            return f'{n / 1_000:.1f}K'
        return str(n)

    # -- update helpers ----------------------------------------------------

    def update_model(self, model: str) -> None:
        self.state.model = model

    def update_tokens(self, used: int, limit: int) -> None:
        self.state.context_tokens = used
        self.state.context_limit = limit

    def update_cost(self, cost_usd: float) -> None:
        self.state.cost_usd = cost_usd

    def update_ledger(self, status: str) -> None:
        self.state.ledger_status = status

    def update_from_llm_metrics(self, metrics: Any) -> None:
        if metrics is None:
            return

        if hasattr(metrics, 'accumulated_cost'):
            self.state.cost_usd = float(
                getattr(metrics, 'accumulated_cost', 0.0) or 0.0
            )

            usages = getattr(metrics, 'token_usages', []) or []
            self.state.llm_calls = len(usages)

            accumulated_usage = getattr(metrics, 'accumulated_token_usage', None)
            if accumulated_usage is not None and any(
                int(getattr(accumulated_usage, field_name, 0) or 0) > 0
                for field_name in (
                    'prompt_tokens',
                    'completion_tokens',
                    'cache_read_tokens',
                    'cache_write_tokens',
                    'context_window',
                )
            ):
                prompt_tokens = int(getattr(accumulated_usage, 'prompt_tokens', 0) or 0)
                completion_tokens = int(
                    getattr(accumulated_usage, 'completion_tokens', 0) or 0
                )
                cache_read_tokens = int(
                    getattr(accumulated_usage, 'cache_read_tokens', 0) or 0
                )
                cache_write_tokens = int(
                    getattr(accumulated_usage, 'cache_write_tokens', 0) or 0
                )
                self.state.context_tokens = (
                    prompt_tokens
                    + completion_tokens
                    + cache_read_tokens
                    + cache_write_tokens
                )
                self.state.context_limit = int(
                    getattr(accumulated_usage, 'context_window', 0) or 0
                )
                return

            usages = getattr(metrics, 'token_usages', []) or []
            if usages:
                latest = usages[-1]
                self.state.context_tokens = int(
                    getattr(latest, 'prompt_tokens', 0) or 0
                ) + int(getattr(latest, 'completion_tokens', 0) or 0)
                self.state.context_limit = int(
                    getattr(latest, 'context_window', 0) or 0
                )
            return

        if isinstance(metrics, dict):
            if 'accumulated_cost' in metrics:
                self.state.cost_usd = float(metrics['accumulated_cost'] or 0.0)
            usages = metrics.get('token_usages', [])
            if usages:
                latest = usages[-1] if isinstance(usages, list) else usages
                if isinstance(latest, dict):
                    total = latest.get('prompt_tokens', 0) + latest.get(
                        'completion_tokens', 0
                    )
                    self.state.context_tokens = total
                    self.state.context_limit = latest.get('context_window', 0)

    def plain_text(self) -> str:
        return self._format().plain

    def render_line(self, console: Console) -> None:
        """Print the HUD as a single bottom-of-screen line."""
        width = console.width
        bar = self._format()
        pad = max(0, width - len(bar.plain) - 2)
        console.print(
            Text('  ') + bar + Text(' ' * pad),
            style='on grey15',
            highlight=False,
            end='',
        )
        console.print()
