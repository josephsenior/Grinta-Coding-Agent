"""Persistent footer status bar — the HUD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

import backend


@dataclass
class HUDState:
    """Mutable state backing the HUD bar."""

    model: str = '(not set)'
    context_tokens: int = 0
    context_limit: int = 0
    cost_usd: float = 0.0
    ledger_status: str = 'Healthy'
    llm_calls: int = 0
    #: None until engine bootstrap (incl. MCP) has finished; then connected MCP client count.
    mcp_servers: int | None = None
    #: Agent lifecycle state label shown in the branded row (e.g. 'Running', 'Ready').
    agent_state_label: str = 'Ready'
    #: Autonomy level label (e.g. 'balanced', 'full', 'supervised').
    autonomy_level: str = 'balanced'
    #: True when token usage shown in HUD is estimated rather than provider-reported.
    token_usage_estimated: bool = False
    #: Resolved project/workspace root (absolute path) for CLI status display.
    workspace_path: str = ''


class HUDBar:
    """Renderable footer bar: [Provider / Model] | [Context] | [Cost] | [LLM calls] | [State]."""

    def __init__(self) -> None:
        self.state = HUDState()
        self._bundled_skill_count = HUDBar.count_bundled_playbook_skills()

    @property
    def bundled_skill_count(self) -> int:
        """Count of bundled ``.md`` playbooks under ``backend/playbooks/`` (see :meth:`count_bundled_playbook_skills`)."""
        return self._bundled_skill_count

    @staticmethod
    def count_bundled_playbook_skills() -> int:
        """Markdown playbooks shipped under ``backend/playbooks/`` (excludes ``README.md``)."""
        try:
            root = Path(backend.__file__).resolve().parent / 'playbooks'
            if not root.is_dir():
                return 0
            return sum(
                1
                for p in root.iterdir()
                if p.is_file()
                and p.suffix.lower() == '.md'
                and p.name.lower() != 'readme.md'
            )
        except OSError:
            return 0

    @staticmethod
    def _format_mcp_servers_label(n: int | None) -> str:
        if n is None:
            return 'MCP servers —'
        if n == 1:
            return '1 MCP server'
        return f'{n} MCP servers'

    @staticmethod
    def _format_skills_label(count: int) -> str:
        if count == 1:
            return '1 skill'
        return f'{count} skills'

    @staticmethod
    def ellipsize_path(path: str, max_len: int) -> str:
        """Shorten *path* for narrow terminals; keep the tail (folder name)."""
        if max_len < 8 or not path or len(path) <= max_len:
            return path
        # Prefer single ellipsis + tail so the leaf directory stays visible.
        tail = max_len - 1
        return '…' + path[-tail:]

    @staticmethod
    def describe_model(model: str | None) -> tuple[str, str]:
        """Return a user-facing provider/model pair from a routing model id."""
        raw = (model or '').strip()
        if not raw or raw == '(not set)':
            return '(not set)', '(not set)'

        try:
            from backend.inference.provider_resolver import get_resolver

            resolver = get_resolver()
            stripped = resolver.strip_provider_prefix(raw)
            provider = resolver.resolve_provider(stripped)
            display_model = resolver.strip_provider_prefix(stripped)
            return provider, display_model
        except Exception:
            if '/' in raw:
                provider, display_model = raw.split('/', 1)
                return provider.lower(), display_model or '(not set)'
            return '(unknown)', raw

    # -- rich renderable protocol ------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = options.max_width
        # Use compact if terminal is narrow or if the full bar would overflow.
        use_compact = width < 80 or self._full_bar_length() > width - 2
        bar = self._format_compact() if use_compact else self._format()
        yield bar

    # Shared tight bullet separator. Matches the live branded row so the
    # committed footer and the in-progress footer feel like the same bar.
    _SEP_TEXT = ' · '
    _SEP_STYLE = '#3a5368'

    def _full_bar_length(self) -> int:
        """Approximate character length of the full-format HUD bar."""
        provider, model = self.describe_model(self.state.model)
        ctx = self._format_tokens(self.state.context_tokens)
        lim = (
            self._format_tokens(self.state.context_limit)
            if self.state.context_limit
            else '?'
        )
        token_display = (
            f'{ctx} tokens' if self.state.context_limit == 0 else f'{ctx}/{lim}'
        )
        if self.state.token_usage_estimated:
            token_display += ' est'
        mcp_label = self._format_mcp_servers_label(self.state.mcp_servers)
        skills_label = self._format_skills_label(self._bundled_skill_count)
        model_display = (
            model if provider in {'(not set)', '(unknown)'} else f'{provider}/{model}'
        )
        parts = [
            f' {model_display}',
            f'{self._SEP_TEXT}{token_display}',
            f'{self._SEP_TEXT}${self.state.cost_usd:.4f}',
            f'{self._SEP_TEXT}{self.state.llm_calls} calls',
            f'{self._SEP_TEXT}{mcp_label}',
            f'{self._SEP_TEXT}{skills_label}',
            f'{self._SEP_TEXT}{self.state.ledger_status}',
        ]
        return sum(len(p) for p in parts) + 1  # +1 for leading space

    def _format(self) -> Text:
        provider, model = self.describe_model(self.state.model)
        ctx = self._format_tokens(self.state.context_tokens)
        lim = (
            self._format_tokens(self.state.context_limit)
            if self.state.context_limit
            else '?'
        )
        # Show a clean placeholder before the first LLM call.
        if self.state.context_tokens == 0 and self.state.context_limit == 0:
            token_display = '0 tokens'
        elif self.state.context_limit == 0:
            token_display = f'{ctx} tokens'
        else:
            token_display = f'{ctx}/{lim}'
        if self.state.token_usage_estimated:
            token_display += ' est'
        mcp_label = self._format_mcp_servers_label(self.state.mcp_servers)
        skills_label = self._format_skills_label(self._bundled_skill_count)
        # Combined "provider/model" — the explicit "provider:" and "model:"
        # labels were visual weight without information gain.
        if provider in {'(not set)', '(unknown)'}:
            model_display = model
        else:
            model_display = f'{provider}/{model}'
        SEP = (self._SEP_TEXT, self._SEP_STYLE)
        parts = [
            (' ', ''),
            (model_display, 'bold #dbe7f3'),
            SEP,
            (token_display, '#b4c4d5'),
            SEP,
            (f'${self.state.cost_usd:.4f}', '#b4c4d5'),
            SEP,
            (f'{self.state.llm_calls} calls', '#b4c4d5'),
            SEP,
            (mcp_label, '#b4c4d5'),
            SEP,
            (skills_label, '#b4c4d5'),
            SEP,
            (self.state.ledger_status, self._ledger_style()),
        ]
        txt = Text()
        for content, style in parts:
            txt.append(content, style=style)
        return txt

    def _format_compact(self) -> Text:
        """Compact format for narrow terminals (< 80 cols)."""
        provider, model = self.describe_model(self.state.model)
        ctx = self._format_tokens(self.state.context_tokens)
        if self.state.context_tokens == 0 and self.state.context_limit == 0:
            token_display = '0t'
        elif self.state.context_limit == 0:
            token_display = f'{ctx}t'
        else:
            token_display = ctx
        if self.state.token_usage_estimated:
            token_display += '~'
        mcp_short = (
            '?'
            if self.state.mcp_servers is None
            else str(min(self.state.mcp_servers, 99))
        )
        sk_short = str(min(self._bundled_skill_count, 99))
        if provider in {'(not set)', '(unknown)'}:
            model_display = model
        else:
            model_display = f'{provider}/{model}'
        # Compact glyphs: ``MCP·N`` / ``sk·N`` read faster than ``mN`` / ``kN``.
        parts = [
            (
                model_display,
                'dim',
            ),
            (' ', 'grey27'),
            (token_display, 'dim'),
            (' ', 'grey27'),
            (f'${self.state.cost_usd:.3f}', 'dim'),
            (' ', 'grey27'),
            (f'MCP·{mcp_short}', 'dim'),
            (' ', 'grey27'),
            (f'sk·{sk_short}', 'dim'),
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
            'Starting': '◌',
            'Review': '◆',
            'Paused': '⏸',
            'Error': '✗',
        }
        return mapping.get(self.state.ledger_status, '?')

    def _ledger_style(self) -> str:
        if self.state.ledger_status in {'Healthy', 'Ready', 'Idle', 'Starting'}:
            return '#8fdfb1 bold'
        if self.state.ledger_status == 'Review':
            return '#fcd34d bold'
        if self.state.ledger_status == 'Paused':
            return '#fcd34d'
        return '#fca5a5 bold'

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

    def update_mcp_servers(self, count: int) -> None:
        """Set connected MCP server count (0 when MCP is enabled but none connected)."""
        self.state.mcp_servers = max(0, int(count))

    def update_agent_state(self, label: str) -> None:
        """Update the agent state label shown in the branded row."""
        self.state.agent_state_label = label

    def update_autonomy(self, level: str) -> None:
        """Update the autonomy level shown in the branded row."""
        self.state.autonomy_level = level

    def update_workspace(self, root: str | Path | None) -> None:
        """Set resolved workspace path for footer / Live HUD (empty if unknown)."""
        if root is None or root == '':
            self.state.workspace_path = ''
            return
        try:
            self.state.workspace_path = str(Path(root).expanduser().resolve())
        except (OSError, ValueError):
            self.state.workspace_path = str(Path(str(root)))

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
            resolved_calls = self._resolve_call_count(
                usages=usages,
                response_latencies=response_latencies,
                costs=costs,
                accumulated_usage=accumulated_usage,
                accumulated_cost=accumulated_cost,
            )
            # Never let metrics with no usage data overwrite a call count that
            # was already incremented (e.g. by _handle_streaming_chunk).
            self.state.llm_calls = max(self.state.llm_calls, resolved_calls)

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
                self.state.token_usage_estimated = bool(
                    getattr(accumulated_usage, 'usage_estimated', False)
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
                self.state.token_usage_estimated = bool(
                    getattr(latest, 'usage_estimated', False)
                )
            return

        if isinstance(metrics, dict):
            accumulated_cost = float(metrics.get('accumulated_cost') or 0.0)
            self.state.cost_usd = accumulated_cost
            usages = metrics.get('token_usages', [])
            accumulated_usage = metrics.get('accumulated_token_usage')
            resolved_calls = self._resolve_call_count(
                usages=usages if isinstance(usages, list) else [],
                response_latencies=metrics.get('response_latencies', []),
                costs=metrics.get('costs', []),
                accumulated_usage=accumulated_usage,
                accumulated_cost=accumulated_cost,
            )
            self.state.llm_calls = max(self.state.llm_calls, resolved_calls)

            if isinstance(accumulated_usage, dict):
                total = (
                    int(accumulated_usage.get('prompt_tokens', 0) or 0)
                    + int(accumulated_usage.get('completion_tokens', 0) or 0)
                    + int(accumulated_usage.get('cache_read_tokens', 0) or 0)
                    + int(accumulated_usage.get('cache_write_tokens', 0) or 0)
                )
                if (
                    total > 0
                    or int(accumulated_usage.get('context_window', 0) or 0) > 0
                ):
                    self.state.context_tokens = total
                    self.state.context_limit = int(
                        accumulated_usage.get('context_window', 0) or 0
                    )
                    self.state.token_usage_estimated = bool(
                        accumulated_usage.get('usage_estimated', False)
                    )
                    return

            if usages:
                latest = usages[-1] if isinstance(usages, list) else usages
                if isinstance(latest, dict):
                    total = int(latest.get('prompt_tokens', 0) or 0) + int(
                        latest.get('completion_tokens', 0) or 0
                    )
                    self.state.context_tokens = total
                    self.state.context_limit = int(latest.get('context_window', 0) or 0)
                    self.state.token_usage_estimated = bool(
                        latest.get('usage_estimated', False)
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
