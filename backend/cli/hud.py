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
    """Renderable footer bar: [Model] | [Context] | [Cost] | [LLM calls] | [State]."""

    def __init__(self) -> None:
        self.state = HUDState()

    # -- rich renderable protocol ------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = options.max_width
        bar = self._format_compact() if width < 80 else self._format()

        pad = max(0, width - len(bar.plain))
        line = Text(' ') + bar + Text(' ' * pad)
        line.stylize('on grey11')
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
            token_display = '0 tkns'
        elif self.state.context_limit == 0:
            token_display = f'{ctx} tkns'
        else:
            token_display = f'{ctx}/{lim}'
        parts = [
            (self.state.model, 'bright_black'),
            (' │ ', 'grey27'),
            (token_display, 'bright_black'),
            (' │ ', 'grey27'),
            (f'${self.state.cost_usd:.4f}', 'bright_black'),
            (' │ ', 'grey27'),
            (f'{self.state.llm_calls} calls', 'bright_black'),
            (' │ ', 'grey27'),
            (self.state.ledger_status, self._ledger_style()),
        ]
        txt = Text()
        for content, style in parts:
            txt.append(content, style=style)
        return txt

    def _format_compact(self) -> Text:
        """Compact format for narrow terminals (< 80 cols)."""
        ctx = self._format_tokens(self.state.context_tokens)
        if self.state.context_tokens == 0 and self.state.context_limit == 0:
            token_display = '0t'
        elif self.state.context_limit == 0:
            token_display = f'{ctx}t'
        else:
            token_display = ctx
        parts = [
            (
                self.state.model.rsplit('/', maxsplit=1)[-1][:12],
                'bright_black',
            ),  # last segment, truncated
            (' ', 'grey27'),
            (token_display, 'bright_black'),
            (' ', 'grey27'),
            (f'${self.state.cost_usd:.3f}', 'bright_black'),
            (' ', 'grey27'),
            (self._ledger_icon(), self._ledger_style()),
        ]
        txt = Text()
        for content, style in parts:
            txt.append(content, style=style)
        return txt

    def _ledger_icon(self) -> str:
        """Single-char status icon for compact mode."""
        mapping = {
            'Healthy': '●',
            'Ready': '○',
            'Idle': '○',
            'Review': '◆',
            'Paused': '⏸',
            'Error': '✗',
        }
        return mapping.get(self.state.ledger_status, '?')

    def _ledger_style(self) -> str:
        if self.state.ledger_status in {'Healthy', 'Ready', 'Idle'}:
            return 'bright_black'
        if self.state.ledger_status == 'Review':
            return 'yellow'
        if self.state.ledger_status == 'Paused':
            return 'bright_black'
        return 'red'

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

    @staticmethod
    def _has_usage_signal(usage: Any) -> bool:
        if usage is None:
            return False
        return any(
            int(getattr(usage, field_name, 0) or 0) > 0
            for field_name in (
                'prompt_tokens',
                'completion_tokens',
                'cache_read_tokens',
                'cache_write_tokens',
                'context_window',
            )
        )

    def _resolve_call_count(
        self,
        *,
        usages: list[Any] | None,
        response_latencies: list[Any] | None = None,
        costs: list[Any] | None = None,
        accumulated_usage: Any = None,
        accumulated_cost: float = 0.0,
    ) -> int:
        usage_count = len(usages or [])
        latency_count = len(response_latencies or [])
        cost_count = len(costs or [])
        call_count = max(usage_count, latency_count, cost_count)
        if call_count == 0 and (
            self._has_usage_signal(accumulated_usage) or accumulated_cost > 0.0
        ):
            return 1
        return call_count

    def update_from_llm_metrics(self, metrics: Any) -> None:
        if metrics is None:
            return

        if hasattr(metrics, 'accumulated_cost'):
            accumulated_cost = float(getattr(metrics, 'accumulated_cost', 0.0) or 0.0)
            self.state.cost_usd = accumulated_cost

            usages = getattr(metrics, 'token_usages', []) or []
            response_latencies = getattr(metrics, 'response_latencies', []) or []
            costs = getattr(metrics, 'costs', []) or []
            accumulated_usage = getattr(metrics, 'accumulated_token_usage', None)
            self.state.llm_calls = self._resolve_call_count(
                usages=usages,
                response_latencies=response_latencies,
                costs=costs,
                accumulated_usage=accumulated_usage,
                accumulated_cost=accumulated_cost,
            )

            if self._has_usage_signal(accumulated_usage):
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
            accumulated_cost = float(metrics.get('accumulated_cost') or 0.0)
            self.state.cost_usd = accumulated_cost
            usages = metrics.get('token_usages', [])
            accumulated_usage = metrics.get('accumulated_token_usage')
            self.state.llm_calls = self._resolve_call_count(
                usages=usages if isinstance(usages, list) else [],
                response_latencies=metrics.get('response_latencies', []),
                costs=metrics.get('costs', []),
                accumulated_usage=accumulated_usage,
                accumulated_cost=accumulated_cost,
            )

            if isinstance(accumulated_usage, dict):
                total = (
                    int(accumulated_usage.get('prompt_tokens', 0) or 0)
                    + int(accumulated_usage.get('completion_tokens', 0) or 0)
                    + int(accumulated_usage.get('cache_read_tokens', 0) or 0)
                    + int(accumulated_usage.get('cache_write_tokens', 0) or 0)
                )
                if total > 0 or int(accumulated_usage.get('context_window', 0) or 0) > 0:
                    self.state.context_tokens = total
                    self.state.context_limit = int(
                        accumulated_usage.get('context_window', 0) or 0
                    )
                    return

            if usages:
                latest = usages[-1] if isinstance(usages, list) else usages
                if isinstance(latest, dict):
                    total = (
                        int(latest.get('prompt_tokens', 0) or 0)
                        + int(latest.get('completion_tokens', 0) or 0)
                    )
                    self.state.context_tokens = total
                    self.state.context_limit = int(
                        latest.get('context_window', 0) or 0
                    )
            return

    def plain_text(self) -> str:
        return self._format().plain

    def render_line(self, console: Console) -> None:
        """Print the HUD as a single bottom-of-screen line."""
        width = console.width
        bar = self._format_compact() if width < 80 else self._format()
        pad = max(0, width - len(bar.plain) - 2)
        console.print(
            Text('  ') + bar + Text(' ' * pad),
            style='on grey15',
            highlight=False,
            end='',
        )
        console.print()
