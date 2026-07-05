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
    #: Total billed/processed tokens across recorded LLM calls.
    total_tokens: int = 0
    #: Current context-window pressure. This is the largest prompt/context size
    #: observed since the most recent condensation, not cumulative token spend.
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
    #: Interaction mode label (chat, plan, agent).
    interaction_mode: str = 'agent'
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
        self._context_usage_ignore_prefix = 0
        self._observed_usage_count = 0

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
    def compact_workspace_label(path: str, max_len: int = 28) -> str:
        """Show the leaf directory name with a leading ellipsis when nested."""
        raw = (path or '').strip()
        if not raw or max_len < 2:
            return raw
        normalized = raw.replace('\\', '/').rstrip('/')
        parts = [part for part in normalized.split('/') if part and part != '.']
        if not parts:
            return raw[:max_len]
        leaf = parts[-1]
        if len(parts) == 1:
            return leaf if len(leaf) <= max_len else leaf[:max_len]
        prefix = '…/'
        budget = max_len - len(prefix)
        if budget < 1:
            return leaf[:max_len]
        if len(leaf) <= budget:
            return f'{prefix}{leaf}'
        return f'{prefix}{leaf[:budget]}'

    @staticmethod
    def _describe_model_via_resolver(raw: str) -> tuple[str, str]:
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

    @staticmethod
    def describe_model(model: str | None) -> tuple[str, str]:
        """Return a user-facing provider/model pair from a routing model id."""
        raw = (model or '').strip()
        if not raw or raw == '(not set)':
            return '(not set)', '(not set)'

        parts = [part.strip() for part in raw.split('/') if part.strip()]
        if len(parts) >= 3:
            client = parts[0].lower()
            provider = parts[1].lower()
            display_model = '/'.join(parts[2:]) or '(not set)'
            if provider in {'', '(not set)'}:
                provider = client
            return provider, display_model
        if len(parts) == 2:
            return parts[0].lower(), parts[1]

        return HUDBar._describe_model_via_resolver(raw)

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
        from backend.cli.display.status_chrome import (
            rich_compact_hud_line,
            status_fields_from_hud,
        )

        fields = status_fields_from_hud(self.state, self._bundled_skill_count)
        return rich_compact_hud_line(
            fields, minimal=self._minimal_mode, term_width=term_width
        )

    def _format_bar_minimal(self) -> Text:
        """Ultra-minimal HUD: just model, tokens, cost, state."""
        from backend.cli.display.status_chrome import status_fields_from_hud

        fields = status_fields_from_hud(self.state, self._bundled_skill_count)

        parts = []
        if fields.model_display and fields.model_display != '(not set)':
            parts.append(fields.model_display)

        parts.append(f'{fields.token_display_compact}t')

        if fields.cost_usd > 0:
            parts.append(f'${fields.cost_usd:.3f}')

        parts.append(fields.agent_state_label)

        return Text(' | '.join(parts), style='#b4c4d5')

    def _ledger_icon(self) -> str:
        """Single-char ledger glyph (tests and callers that inspect HUD state)."""
        from backend.cli.display.status_chrome import ledger_icon

        return ledger_icon(self.state.ledger_status)

    @staticmethod
    def _format_tokens(n: int) -> str:
        if n >= 1_000_000:
            val = n / 1_000_000
            return f'{int(val)}M' if val.is_integer() else f'{val:.1f}M'
        if n >= 1_000:
            val = n / 1_000
            return f'{int(val)}K' if val.is_integer() else f'{val:.1f}K'
        return str(n)

    @staticmethod
    def resolve_context_limit_for_model(model: str) -> int:
        """Best-effort context window for HUD display before usage metrics arrive."""
        raw = (model or '').strip()
        if not raw or raw == '(not set)':
            return 1_000_000
        try:
            from backend.inference.catalog.catalog_loader import (
                get_context_window_tokens,
            )

            limit = int(get_context_window_tokens(raw) or 0)
            if limit > 0:
                return limit
        except Exception:
            pass
        return 1_000_000

    # -- update helpers ----------------------------------------------------

    def update_model(self, model: str) -> None:
        self.state.model = model
        if self.state.context_limit <= 0:
            self.state.context_limit = self.resolve_context_limit_for_model(model)

    @staticmethod
    def _usage_context_pressure(usage: Any) -> int:
        """Best-effort current prompt size for HUD context pressure."""
        if isinstance(usage, dict):
            full = int(usage.get('full_request_tokens', 0) or 0)
            prompt = int(usage.get('prompt_tokens', 0) or 0)
        else:
            full = int(getattr(usage, 'full_request_tokens', 0) or 0)
            prompt = int(getattr(usage, 'prompt_tokens', 0) or 0)
        return full if full > prompt else prompt

    @staticmethod
    def _usage_context_limit(usage: Any, *, fallback: int = 0) -> int:
        """Return total context window for HUD display."""
        if isinstance(usage, dict):
            window = int(usage.get('context_window', 0) or 0)
        else:
            window = int(getattr(usage, 'context_window', 0) or 0)
        return window if window > 0 else fallback

    @staticmethod
    def _prompt_token_accounting_from_extra(extra_data: Any) -> dict[str, Any] | None:
        if not isinstance(extra_data, dict):
            return None
        raw = extra_data.get('prompt_token_accounting')
        return raw if isinstance(raw, dict) else None

    def apply_prompt_token_accounting(self, accounting: dict[str, Any] | None) -> None:
        """Apply the latest internal prompt composition estimate to HUD context pressure."""
        if not isinstance(accounting, dict):
            return
        full = accounting.get('full_request_tokens')
        if full is not None and not isinstance(full, bool):
            try:
                parsed_full = int(full)
            except (TypeError, ValueError):
                parsed_full = 0
            if parsed_full > 0:
                self.state.context_tokens = parsed_full
        window = accounting.get('context_window')
        if window is not None and not isinstance(window, bool):
            try:
                parsed_window = int(window)
            except (TypeError, ValueError):
                parsed_window = 0
            if parsed_window > 0:
                self.state.context_limit = parsed_window
        elif self.state.context_limit <= 0:
            self.state.context_limit = self.resolve_context_limit_for_model(
                self.state.model
            )

    def update_tokens(self, used: int, limit: int) -> None:
        self.state.context_tokens = used
        self.state.context_limit = limit

    @staticmethod
    def _usage_total_tokens(usage: Any) -> int:
        if usage is None:
            return 0
        prompt = int(getattr(usage, 'prompt_tokens', 0) or 0)
        completion = int(getattr(usage, 'completion_tokens', 0) or 0)
        return prompt + completion

    @staticmethod
    def _dict_usage_total_tokens(usage: dict[str, Any] | None) -> int:
        if not isinstance(usage, dict):
            return 0
        prompt = int(usage.get('prompt_tokens', 0) or 0)
        completion = int(usage.get('completion_tokens', 0) or 0)
        return prompt + completion

    def _resolve_total_tokens_from_object_metrics(
        self,
        usages: list[Any] | None,
        accumulated_usage: Any,
    ) -> int:
        total = self._usage_total_tokens(accumulated_usage)
        if total > 0:
            return total
        return sum(self._usage_total_tokens(usage) for usage in usages or [])

    def _resolve_total_tokens_from_dict_metrics(
        self,
        usages: list[Any] | None,
        accumulated_usage: dict[str, Any] | None,
    ) -> int:
        total = self._dict_usage_total_tokens(accumulated_usage)
        if total > 0:
            return total
        summed = 0
        for usage in usages or []:
            if isinstance(usage, dict):
                summed += self._dict_usage_total_tokens(usage)
        return summed

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

    def update_interaction_mode(self, mode: str) -> None:
        """Update the interaction mode shown in status chrome."""
        from backend.core.interaction_modes import normalize_interaction_mode

        self.state.interaction_mode = normalize_interaction_mode(mode)

    def update_condensation_count(self, count: int) -> None:
        """Update the context condensation count displayed in HUD."""
        next_count = max(0, int(count))
        if next_count > self.state.condensation_count:
            # A condensation starts a new context-window epoch. Keep cost/call
            # totals, but let the next post-condensation prompt establish the
            # new context pressure instead of reusing the pre-condense high-water
            # mark from cumulative metrics.
            self.state.context_tokens = 0
            self._context_usage_ignore_prefix = self._observed_usage_count
        self.state.condensation_count = next_count

    @staticmethod
    def estimate_full_request_from_post_compact(extra_data: Any) -> int | None:
        """Estimate full prompt size from the post-compaction boundary snapshot."""
        if not isinstance(extra_data, dict):
            return None
        pipe = extra_data.get('context_pipeline_state')
        if not isinstance(pipe, dict):
            return None
        post_compact = pipe.get('post_compact_true_tokens')
        if not isinstance(post_compact, int) or post_compact <= 0:
            return None
        accounting = HUDBar._prompt_token_accounting_from_extra(extra_data) or {}
        fixed = 0
        for key in (
            'static_prompt_tokens',
            'context_packet_tokens',
            'tool_schema_tokens',
        ):
            value = accounting.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                fixed += parsed
        return post_compact + fixed

    def apply_post_compaction_context(self, extra_data: Any) -> None:
        """Refresh HUD context pressure after a committed compaction."""
        estimate = self.estimate_full_request_from_post_compact(extra_data)
        if estimate is not None:
            self.state.context_tokens = estimate
        else:
            self.state.context_tokens = 0
        self._context_usage_ignore_prefix = self._observed_usage_count
        self.state.token_usage_estimated = True

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
        resolved_total_tokens = self._resolve_total_tokens_from_object_metrics(
            usages,
            accumulated_usage,
        )
        if resolved_total_tokens > 0:
            self.state.total_tokens = resolved_total_tokens
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

        if usages:
            self._apply_object_context_usages(usages)
            return
        if self._has_usage_signal(accumulated_usage):
            self._apply_object_accumulated_usage(accumulated_usage)

    def _apply_object_accumulated_usage(self, accumulated_usage: Any) -> None:
        prompt_tokens = int(getattr(accumulated_usage, 'prompt_tokens', 0) or 0)
        completion_tokens = int(getattr(accumulated_usage, 'completion_tokens', 0) or 0)
        self.state.total_tokens = prompt_tokens + completion_tokens
        self.state.context_limit = int(
            getattr(accumulated_usage, 'context_window', 0) or 0
        )
        self.state.token_usage_estimated = bool(
            getattr(accumulated_usage, 'usage_estimated', False)
        )

    def _object_usage_context_slice(self, usages: list[Any]) -> list[Any]:
        usage_count = len(usages)
        start = self._context_usage_ignore_prefix
        if start > usage_count:
            # The caller supplied a fresh/diff metrics object rather than the
            # cumulative metrics list. Treat all entries as current-epoch data.
            start = 0
            self._context_usage_ignore_prefix = 0
        self._observed_usage_count = max(self._observed_usage_count, usage_count)
        return list(usages[start:])

    def _apply_object_context_usages(self, usages: list[Any]) -> None:
        relevant = self._object_usage_context_slice(usages)
        if not relevant:
            return
        best_prompt = self.state.context_tokens
        best_estimated = self.state.token_usage_estimated
        latest_limit = self.state.context_limit
        for usage in relevant:
            prompt_tokens = self._usage_context_pressure(usage)
            context_limit = self._usage_context_limit(
                usage, fallback=self.state.context_limit
            )
            if context_limit > 0:
                latest_limit = context_limit
            if prompt_tokens >= best_prompt:
                best_prompt = prompt_tokens
                best_estimated = bool(getattr(usage, 'usage_estimated', False))
        self.state.context_tokens = best_prompt
        self.state.context_limit = latest_limit
        self.state.token_usage_estimated = best_estimated

    def _apply_object_latest_usage(self, latest: Any) -> None:
        self._apply_object_context_usages([latest])

    def _update_from_dict_metrics_resolve_context(
        self,
        usages: Any,
        accumulated_usage: Any,
    ) -> None:
        if not usages:
            if isinstance(
                accumulated_usage, dict
            ) and self._apply_dict_accumulated_usage(
                accumulated_usage,
            ):
                return
            return
        latest = usages[-1] if isinstance(usages, list) else usages
        if isinstance(latest, dict):
            self._apply_dict_context_usages(usages)

    def _update_from_dict_metrics(self, metrics: dict[str, Any]) -> None:
        accumulated_cost = float(metrics.get('accumulated_cost') or 0.0)
        self.state.cost_usd = accumulated_cost
        usages = metrics.get('token_usages', [])
        accumulated_usage = metrics.get('accumulated_token_usage')
        resolved_total_tokens = self._resolve_total_tokens_from_dict_metrics(
            usages if isinstance(usages, list) else [],
            accumulated_usage if isinstance(accumulated_usage, dict) else None,
        )
        if resolved_total_tokens > 0:
            self.state.total_tokens = resolved_total_tokens
        resolved_calls = self._resolve_call_count(
            usages=usages if isinstance(usages, list) else [],
            response_latencies=metrics.get('response_latencies', []),
            costs=metrics.get('costs', []),
            accumulated_usage=accumulated_usage,
            accumulated_cost=accumulated_cost,
        )
        self.state.llm_calls = max(self.state.llm_calls, resolved_calls)
        self._update_from_dict_metrics_resolve_context(usages, accumulated_usage)

    def _apply_dict_accumulated_usage(
        self,
        accumulated_usage: dict[str, Any],
    ) -> bool:
        prompt = int(accumulated_usage.get('prompt_tokens', 0) or 0)
        completion = int(accumulated_usage.get('completion_tokens', 0) or 0)
        if prompt <= 0 and int(accumulated_usage.get('context_window', 0) or 0) <= 0:
            return False
        self.state.total_tokens = prompt + completion
        self.state.context_limit = int(accumulated_usage.get('context_window', 0) or 0)
        self.state.token_usage_estimated = bool(
            accumulated_usage.get('usage_estimated', False)
        )
        return True

    def _dict_usage_context_slice(self, usages: list[Any]) -> list[dict[str, Any]]:
        usage_count = len(usages)
        start = self._context_usage_ignore_prefix
        if start > usage_count:
            start = 0
            self._context_usage_ignore_prefix = 0
        self._observed_usage_count = max(self._observed_usage_count, usage_count)
        return [usage for usage in usages[start:] if isinstance(usage, dict)]

    def _apply_dict_context_usages(self, usages: list[Any]) -> None:
        relevant = self._dict_usage_context_slice(usages)
        if not relevant:
            return
        best_prompt = self.state.context_tokens
        best_estimated = self.state.token_usage_estimated
        latest_limit = self.state.context_limit
        for usage in relevant:
            prompt_tokens = self._usage_context_pressure(usage)
            context_limit = self._usage_context_limit(
                usage, fallback=self.state.context_limit
            )
            if context_limit > 0:
                latest_limit = context_limit
            if prompt_tokens >= best_prompt:
                best_prompt = prompt_tokens
                best_estimated = bool(usage.get('usage_estimated', False))
        self.state.context_tokens = best_prompt
        self.state.context_limit = latest_limit
        self.state.token_usage_estimated = best_estimated

    def _apply_dict_latest_usage(self, latest: dict[str, Any]) -> None:
        self._apply_dict_context_usages([latest])

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
