"""Persistent footer status bar — the HUD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

import backend
from backend.cli.theme import HUD_BG


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
    #: Autonomy level label (e.g. 'balanced', 'full', 'conservative').
    autonomy_level: str = 'balanced'
    #: True when token usage shown in HUD is estimated rather than provider-reported.
    token_usage_estimated: bool = False
    #: Resolved project/workspace root (absolute path) for CLI status display.
    workspace_path: str = ''
    #: Minimal mode strips borders and reduces information for cleaner display.
    minimal_mode: bool = False
    #: Number of context condensations that have occurred in this session.
    condensation_count: int = 0


class HUDBar:
    """Renderable footer bar: [Provider / Model] | [Context] | [Cost] | [LLM calls] | [State]."""

    def __init__(self) -> None:
        self.state = HUDState()
        self._bundled_skill_count = HUDBar.count_bundled_playbook_skills()
        self._minimal_mode = False

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
        """Shorten *path* for narrow terminals.

        Strategy: keep the first path segment (drive / repo root) **and** the
        tail (current directory) so users can recognise both the project they
        are in and where they are inside it. ``a/b/c/d/e/f`` shortens to
        ``a/…/e/f`` rather than ``…c/d/e/f`` which loses the project anchor.
        Falls back to a tail-only ellipsis when the budget is too tight to
        preserve both ends.
        """
        if max_len < 8 or not path or len(path) <= max_len:
            return path
        # Pick the canonical separator already used in the path so Windows
        # paths don't suddenly grow forward slashes.
        sep = '\\' if '\\' in path and '/' not in path else '/'
        parts = path.split(sep)
        if len(parts) >= 3:
            head = parts[0] or sep  # preserve leading sep on POSIX absolute paths
            for tail_take in range(min(3, len(parts) - 1), 0, -1):
                tail = sep.join(parts[-tail_take:])
                candidate = f'{head}{sep}…{sep}{tail}'
                if len(candidate) <= max_len:
                    return candidate
        # Fallback: ellipsis + tail keeps the leaf directory visible.
        tail_len = max_len - 1
        return '…' + path[-tail_len:]

    @staticmethod
    def describe_model(model: str | None) -> tuple[str, str]:
        """Return a user-facing provider/model pair from a routing model id."""
        raw = (model or '').strip()
        if not raw or raw == '(not set)':
            return '(not set)', '(not set)'

        parts = [part.strip() for part in raw.split('/') if part.strip()]
        # Preserve explicit client/provider/model routing:
        # - openai/provider/model -> provider + model
        # - provider/model -> provider + model
        # This keeps provider independent from transport client.
        if len(parts) >= 3:
            client = parts[0].lower()
            provider = parts[1].lower()
            display_model = '/'.join(parts[2:]) or '(not set)'
            # If the provider segment is absent/invalid, treat the client as provider.
            if provider in {'', '(not set)'}:
                provider = client
            return provider, display_model
        if len(parts) == 2:
            return parts[0].lower(), parts[1]

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
        yield self._format_bar(term_width=options.max_width)

    def _format(self) -> Text:
        """Single HUD layout (alias for :meth:`_format_bar`)."""
        return self._format_bar()

    def _format_compact(self) -> Text:
        """Deprecated alias for :meth:`_format_bar` — one bar at all widths."""
        return self._format_bar()

    def set_minimal_mode(self, enabled: bool) -> None:
        """Enable or disable minimal mode for cleaner display."""
        self._minimal_mode = enabled
        self.state.minimal_mode = enabled

    @property
    def is_minimal_mode(self) -> bool:
        """Check if minimal mode is enabled."""
        return self._minimal_mode

    def _format_bar(self, *, term_width: int | None = None) -> Text:
        """One dense status line: workspace, model, tokens, cost, MCP, skills, ledger icon.

        In minimal mode, returns an even simpler line with less decoration.
        """
        from backend.cli.status_chrome import (
            rich_compact_hud_line,
            status_fields_from_hud,
        )

        fields = status_fields_from_hud(self.state, self._bundled_skill_count)
        return rich_compact_hud_line(
            fields, minimal=self._minimal_mode, term_width=term_width
        )

    def _format_bar_minimal(self) -> Text:
        """Ultra-minimal HUD: just model, tokens, cost, state."""
        from backend.cli.status_chrome import status_fields_from_hud

        fields = status_fields_from_hud(self.state, self._bundled_skill_count)

        parts = []
        if fields.model_display and fields.model_display != '(not set)':
            parts.append(fields.model_display)

        parts.append(f'{fields.token_display_compact}t')

        if fields.cost_usd > 0:
            parts.append(f'${fields.cost_usd:.2f}')

        parts.append(fields.agent_state_label)

        return Text(' | '.join(parts), style='#b4c4d5')

    def _ledger_icon(self) -> str:
        """Single-char ledger glyph (tests and callers that inspect HUD state)."""
        from backend.cli.status_chrome import ledger_icon

        return ledger_icon(self.state.ledger_status)

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

    def update_condensation_count(self, count: int) -> None:
        """Update the context condensation count displayed in HUD."""
        self.state.condensation_count = max(0, count)

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
            self._update_from_object_metrics(metrics)
            return
        if isinstance(metrics, dict):
            self._update_from_dict_metrics(metrics)

    def _update_from_object_metrics(self, metrics: Any) -> None:
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
            self._apply_object_accumulated_usage(accumulated_usage)
            return
        if usages:
            self._apply_object_latest_usage(usages[-1])

    def _apply_object_accumulated_usage(self, accumulated_usage: Any) -> None:
        prompt_tokens = int(getattr(accumulated_usage, 'prompt_tokens', 0) or 0)
        completion_tokens = int(getattr(accumulated_usage, 'completion_tokens', 0) or 0)
        cache_read_tokens = int(getattr(accumulated_usage, 'cache_read_tokens', 0) or 0)
        cache_write_tokens = int(
            getattr(accumulated_usage, 'cache_write_tokens', 0) or 0
        )
        self.state.context_tokens = (
            prompt_tokens + completion_tokens + cache_read_tokens + cache_write_tokens
        )
        self.state.context_limit = int(
            getattr(accumulated_usage, 'context_window', 0) or 0
        )
        self.state.token_usage_estimated = bool(
            getattr(accumulated_usage, 'usage_estimated', False)
        )

    def _apply_object_latest_usage(self, latest: Any) -> None:
        self.state.context_tokens = int(getattr(latest, 'prompt_tokens', 0) or 0) + int(
            getattr(latest, 'completion_tokens', 0) or 0
        )
        self.state.context_limit = int(getattr(latest, 'context_window', 0) or 0)
        self.state.token_usage_estimated = bool(
            getattr(latest, 'usage_estimated', False)
        )

    def _update_from_dict_metrics(self, metrics: dict[str, Any]) -> None:
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

        if isinstance(accumulated_usage, dict) and self._apply_dict_accumulated_usage(
            accumulated_usage,
        ):
            return
        if usages:
            latest = usages[-1] if isinstance(usages, list) else usages
            if isinstance(latest, dict):
                self._apply_dict_latest_usage(latest)

    def _apply_dict_accumulated_usage(
        self,
        accumulated_usage: dict[str, Any],
    ) -> bool:
        total = (
            int(accumulated_usage.get('prompt_tokens', 0) or 0)
            + int(accumulated_usage.get('completion_tokens', 0) or 0)
            + int(accumulated_usage.get('cache_read_tokens', 0) or 0)
            + int(accumulated_usage.get('cache_write_tokens', 0) or 0)
        )
        if total <= 0 and int(accumulated_usage.get('context_window', 0) or 0) <= 0:
            return False
        self.state.context_tokens = total
        self.state.context_limit = int(accumulated_usage.get('context_window', 0) or 0)
        self.state.token_usage_estimated = bool(
            accumulated_usage.get('usage_estimated', False)
        )
        return True

    def _apply_dict_latest_usage(self, latest: dict[str, Any]) -> None:
        total = int(latest.get('prompt_tokens', 0) or 0) + int(
            latest.get('completion_tokens', 0) or 0
        )
        self.state.context_tokens = total
        self.state.context_limit = int(latest.get('context_window', 0) or 0)
        self.state.token_usage_estimated = bool(latest.get('usage_estimated', False))

    def plain_text(self) -> str:
        return self._format_bar().plain

    def render_line(self, console: Console) -> None:
        """Print the HUD as a single bottom-of-screen line."""
        width = console.width
        bar = self._format_bar(term_width=width)
        pad = max(0, width - len(bar.plain) - 2)
        console.print(
            Text('  ') + bar + Text(' ' * pad),
            style=f'on {HUD_BG}',
            highlight=False,
            end='',
        )
        console.print()
