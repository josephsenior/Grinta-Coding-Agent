from __future__ import annotations

import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

from textual.widgets import (
    Label,
    ListView,
    Select,
    TextArea,
)

from backend.cli.display.hud import HUDBar
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_GREEN_ACCENT,
    NAVY_RED_ACCENT,
    NAVY_RUNNING,
    NAVY_RUNNING_DIM,
    NAVY_TEXT_DIM,
    NAVY_TEXT_SECONDARY,
    NAVY_WAITING,
    NAVY_WAITING_DIM,
    NAVY_YELLOW_ACCENT,
)
from backend.cli.tui.helpers import (
    _strip_ansi,
)
from backend.cli.tui.widgets.small import (
    HUD,
    InputBar,
)
from backend.core.interaction_modes import (
    AGENT_MODE,
    CHAT_MODE,
    PLAN_MODE,
    VISIBLE_INTERACTION_MODES,
    is_chat_mode,
    normalize_interaction_mode,
    resolve_active_interaction_mode,
)


class ScreenStateMixin:
    """State-related methods of GrintaScreen."""

    _TURN_DURATION_STATES = frozenset(
        {'awaiting_user_input', 'finished', 'stopped', 'error', 'ready'}
    )
    _RUNNING_PULSE_BULLETS = ('●', '◉')
    _RUNNING_PULSE_COLORS = (NAVY_RUNNING, NAVY_RUNNING_DIM)
    _WAITING_PULSE_COLORS = (NAVY_WAITING, NAVY_WAITING_DIM)
    _HUD_PULSE_EXACT = frozenset(
        {
            'running',
            'starting',
            'loading',
            'awaiting_user_confirmation',
            'rate_limited',
        }
    )
    _HUD_PULSE_PREFIXES = ('backoff', 'retrying')

    @classmethod
    def _hud_state_should_pulse(cls, raw_state: str | None) -> bool:
        lookup = cls._state_lookup_key(raw_state)
        lookup_norm = lookup.replace(' ', '_')
        if lookup in cls._HUD_PULSE_EXACT or lookup_norm in cls._HUD_PULSE_EXACT:
            return True
        return any(
            lookup.startswith(prefix) or lookup_norm.startswith(prefix)
            for prefix in cls._HUD_PULSE_PREFIXES
        )

    @classmethod
    def _hud_pulse_colors(cls, lookup: str) -> tuple[str, str]:
        if lookup == 'running':
            return cls._RUNNING_PULSE_COLORS
        return cls._WAITING_PULSE_COLORS

    @staticmethod
    def _state_lookup_key(raw_state: str | None) -> str:
        raw = (raw_state or 'Ready').strip()
        lookup_key = raw.lower()
        if lookup_key.startswith('agentstate.'):
            lookup_key = lookup_key[len('agentstate.') :]
        if '.' in lookup_key:
            lookup_key = lookup_key.split('.')[-1]
        return lookup_key

    def _append_turn_duration(self, display_state: str, raw_state: str | None) -> str:
        duration = getattr(self, '_last_turn_duration', None)
        if not duration:
            return display_state
        if self._state_lookup_key(raw_state) not in self._TURN_DURATION_STATES:
            return display_state
        return f'{display_state} [worked for {duration}]'

    @classmethod
    def _resolve_state_display(cls, raw_state: str | None) -> tuple[str, str]:
        raw = (raw_state or 'Ready').strip()
        lookup_key = raw.lower()
        if lookup_key.startswith('agentstate.'):
            lookup_key = lookup_key[len('agentstate.') :]
        if '.' in lookup_key:
            lookup_key = lookup_key.split('.')[-1]

        for prefix in ('backoff', 'retrying'):
            if lookup_key.startswith(prefix):
                return raw, cls._STATE_COLORS[prefix]

        return (
            cls._STATE_LABELS.get(lookup_key, raw or 'Ready'),
            cls._STATE_COLORS.get(lookup_key, NAVY_BRAND),
        )

    def _active_agent_name(self) -> str:
        from backend.core.constants import DEFAULT_AGENT_NAME

        name = getattr(self._config, 'default_agent', None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return DEFAULT_AGENT_NAME

    def _active_agent_config(self) -> Any | None:
        getter = getattr(self._config, 'get_agent_config', None)
        if not callable(getter):
            return None
        try:
            return getter(self._active_agent_name())
        except TypeError:
            return getter()

    def _sidebar_mcp_enabled(self) -> bool:
        mcp = getattr(self._config, 'mcp', None)
        return bool(getattr(mcp, 'enabled', False))

    def _sidebar_lsp_enabled(self) -> bool:
        from backend.core.constants import DEFAULT_AGENT_LSP_QUERY_ENABLED

        agent_config = self._active_agent_config()
        if agent_config is None:
            return DEFAULT_AGENT_LSP_QUERY_ENABLED
        return bool(
            getattr(agent_config, 'enable_lsp_query', DEFAULT_AGENT_LSP_QUERY_ENABLED)
        )

    def _sidebar_debugger_enabled(self) -> bool:
        from backend.core.constants import DEFAULT_AGENT_DEBUGGER_ENABLED

        agent_config = self._active_agent_config()
        if agent_config is None:
            return DEFAULT_AGENT_DEBUGGER_ENABLED
        return bool(
            getattr(agent_config, 'enable_debugger', DEFAULT_AGENT_DEBUGGER_ENABLED)
        )

    def _active_interaction_mode(self) -> str:
        agent_config = self._active_agent_config()
        configured = getattr(agent_config, 'mode', AGENT_MODE)
        active_run_mode = None
        controller = getattr(self, '_controller', None)
        if controller is not None:
            state = getattr(controller, 'state', None)
            extra = getattr(state, 'extra_data', None) if state is not None else None
            if isinstance(extra, dict):
                active_run_mode = extra.get('active_run_mode')
        return resolve_active_interaction_mode(
            active_run_mode=active_run_mode,
            configured_mode=configured,
        )

    def _resolve_workspace_display(self, workspace_path) -> str:
        workspace = str(workspace_path or Path(os.getcwd()))
        try:
            home = str(Path.home())
            if workspace.startswith(home):
                workspace = workspace.replace(home, '~', 1)
        except Exception:
            pass
        return workspace

    def _build_hud_line1(
        self,
        display_state: str,
        state_color: str,
        *,
        raw_state: str | None = None,
    ) -> str:
        lookup = self._state_lookup_key(raw_state)
        if self._hud_state_should_pulse(raw_state):
            pulse_colors = self._hud_pulse_colors(lookup)
            frame = int(getattr(self, '_hud_pulse_frame', 0)) % len(
                self._RUNNING_PULSE_BULLETS
            )
            bullet = self._RUNNING_PULSE_BULLETS[frame]
            bullet_color = pulse_colors[frame]
            state_part = (
                f'[{bullet_color}]{bullet}[/] [{state_color}]{display_state}[/]'
            )
        else:
            state_part = f'[{state_color}]● {display_state}[/]'
        return state_part

    def _tick_hud_running_pulse(self) -> None:
        """Advance the HUD bullet pulse for active/waiting states (cheap label-only refresh)."""
        if self._is_unmounted:
            return
        raw_state = self._hud.state.agent_state_label or 'Ready'
        if not self._hud_state_should_pulse(raw_state):
            if getattr(self, '_hud_pulse_frame', 0) != 0:
                self._hud_pulse_frame = 0
                self._render_hud_bar()
            return
        self._hud_pulse_frame = (int(getattr(self, '_hud_pulse_frame', 0)) + 1) % len(
            self._RUNNING_PULSE_BULLETS
        )
        self._render_hud_bar()

    @staticmethod
    def _build_hud_line2_leading(ws_display: str) -> str:
        return f'[#91abec].Grinta[/]  [{NAVY_TEXT_DIM}]Ws: {ws_display}[/]'

    @staticmethod
    def _build_context_display(used: int, limit: int) -> str:
        display_limit = (
            limit if limit > 0 else HUDBar.resolve_context_limit_for_model('')
        )
        pct = min(100, (used * 100 // display_limit) if display_limit else 0)
        ctx_color = (
            NAVY_GREEN_ACCENT
            if pct < 80
            else NAVY_YELLOW_ACCENT
            if pct < 95
            else NAVY_RED_ACCENT
        )
        from backend.cli.tui._a11y import ascii_glyphs_enabled
        from backend.cli.tui.widgets.glyphs import glyph

        used_label = HUDBar._format_tokens(max(0, used))
        limit_label = HUDBar._format_tokens(display_limit)
        if ascii_glyphs_enabled():
            word = 'low' if pct < 80 else 'med' if pct < 95 else 'high'
            return (
                f'[{NAVY_TEXT_DIM}]Ctx: {used_label}/{limit_label} '
                f'[{pct}% {word}]  '
                f'[{ctx_color}]{glyph("●")}[/][/]'
            )
        return (
            f'[{NAVY_TEXT_DIM}]Ctx: {used_label}/{limit_label} [{pct}%]  '
            f'[{ctx_color}]●[/][/]'
        )

    @staticmethod
    def _visible_autonomy_level(value: object, *, default: str = '') -> str:
        from backend.core.autonomy import normalize_autonomy_level

        level = normalize_autonomy_level(value)
        return level if level in {'conservative', 'balanced', 'full'} else default

    def _runtime_autonomy_level(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                level = self._visible_autonomy_level(
                    getattr(ac, 'autonomy_level', None)
                )
                if level:
                    return level

        agent_config = self._active_agent_config()
        if agent_config is not None:
            level = self._visible_autonomy_level(
                getattr(agent_config, 'autonomy_level', None)
            )
            if level:
                return level

        level = self._visible_autonomy_level(
            getattr(self._config, 'autonomy_level', None)
        )
        if level:
            return level

        return self._visible_autonomy_level(
            getattr(self._hud.state, 'autonomy_level', None),
            default='balanced',
        )

    def _current_autonomy_level(self) -> str:
        """Return the active autonomy level (runtime mirrors settings.json after sync)."""
        runtime = self._runtime_autonomy_level()
        if runtime:
            return runtime

        from backend.cli.settings import get_persisted_autonomy_level

        configured = get_persisted_autonomy_level(self._active_agent_name())
        if configured:
            return configured

        return 'balanced'

    def _mark_hud_select_sync(self, widget_id: str, *values: object) -> None:
        pending = getattr(self, '_hud_select_sync_values', None)
        if not isinstance(pending, dict):
            pending = {}
            self._hud_select_sync_values = pending
        value_set = {str(value) for value in values if value is not Select.BLANK}
        if value_set:
            pending[widget_id] = (value_set, time.monotonic() + 0.5)

    def _consume_hud_select_sync_event(self, widget_id: str, value: object) -> bool:
        pending = getattr(self, '_hud_select_sync_values', None)
        if not isinstance(pending, dict):
            return False
        entry = pending.get(widget_id)
        if entry is None:
            return False
        values, expires_at = entry
        if time.monotonic() > expires_at:
            pending.pop(widget_id, None)
            return False
        text = str(value)
        if text not in values:
            return False
        values.discard(text)
        if values:
            pending[widget_id] = (values, expires_at)
        else:
            pending.pop(widget_id, None)
        return True

    def _sync_hud_autonomy_select(self, hud_bar, autonomy: str) -> None:
        allowed = {'conservative', 'balanced', 'full'}
        if autonomy not in allowed:
            autonomy = self._current_autonomy_level()
        if autonomy not in allowed:
            autonomy = 'balanced'
        try:
            autonomy_select = hud_bar.query_one('#hud-autonomy', Select)
            value_changed = autonomy_select.value != autonomy
            if value_changed:
                self._mark_hud_select_sync(
                    'hud-autonomy',
                    autonomy_select.value,
                    autonomy,
                )
            self._hud_autonomy_syncing = True
            try:
                with autonomy_select.prevent(Select.Changed):
                    if value_changed:
                        autonomy_select.value = autonomy
            finally:
                self._hud_autonomy_syncing = False
        except Exception:
            self._hud_autonomy_syncing = False

    def _sync_hud_mode_select(self, hud_bar) -> None:
        try:
            mode_select = hud_bar.query_one('#hud-mode', Select)
            current_mode = self._active_interaction_mode()
            if current_mode not in VISIBLE_INTERACTION_MODES:
                current_mode = CHAT_MODE if is_chat_mode(current_mode) else AGENT_MODE
            if mode_select.value != current_mode:
                self._mark_hud_select_sync('hud-mode', current_mode)
                self._hud_mode_syncing = True
                try:
                    with mode_select.prevent(Select.Changed):
                        mode_select.value = current_mode
                finally:
                    self._hud_mode_syncing = False
        except Exception:
            self._hud_mode_syncing = False
            pass

    def _current_llm_provider(self) -> str:
        from backend.cli.settings import get_current_provider

        return get_current_provider(self._config) or ''

    def _resolve_hud_model_entry(self) -> Any | None:
        from backend.cli.settings import get_current_model
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.catalog.provider_catalog import (
            build_model_entries_by_provider,
        )

        provider = self._current_llm_provider()
        model = (
            get_current_model(self._config) or str(self._hud.state.model or '').strip()
        )
        if not model or model == '(not set)':
            return None

        fallback = None
        for candidate in build_model_entries_by_provider(provider=provider).get(
            provider or '', []
        ):
            if candidate.name == model:
                fallback = candidate
                break

        return resolve_model_entry_for_capabilities(
            model,
            provider,
            fallback=fallback,
        )

    def _hud_reasoning_select_options(self) -> list[tuple[str, str]]:
        from backend.inference.reasoning import reasoning_effort_display_options

        entry = self._resolve_hud_model_entry()
        options = reasoning_effort_display_options(entry, include_disabled=True)
        if options:
            return options
        return [('Default', '')]

    def _current_reasoning_effort(self) -> str:
        from backend.cli.settings import get_persisted_reasoning_effort

        configured = get_persisted_reasoning_effort().strip().lower()
        if not configured:
            try:
                configured = (
                    (
                        getattr(self._config.get_llm_config(), 'reasoning_effort', None)
                        or ''
                    )
                    .strip()
                    .lower()
                )
            except Exception:
                configured = ''
        allowed = {value for _label, value in self._hud_reasoning_select_options()}
        if configured == 'max' and 'max' not in allowed and 'xhigh' in allowed:
            configured = 'xhigh'
        return configured if configured in allowed else ''

    def _sync_hud_reasoning_select(self, hud_bar) -> None:
        try:
            reasoning_select = hud_bar.query_one('#hud-reasoning', Select)
            options = self._hud_reasoning_select_options()
            current = self._current_reasoning_effort()
            values = {value for _label, value in options}
            if current not in values:
                current = options[0][1]
            options_changed = tuple(reasoning_select._options) != tuple(options)
            value_changed = reasoning_select.value != current
            if options_changed or value_changed:
                first_option = options[0][1] if options else ''
                self._mark_hud_select_sync(
                    'hud-reasoning',
                    reasoning_select.value,
                    first_option,
                    current,
                )
            self._hud_reasoning_syncing = True
            try:
                with reasoning_select.prevent(Select.Changed):
                    if options_changed:
                        reasoning_select.set_options(options)
                    if value_changed:
                        reasoning_select.value = current
            finally:
                self._hud_reasoning_syncing = False
        except Exception:
            self._hud_reasoning_syncing = False

    def _sync_hud_reasoning_visibility(self, hud_bar) -> None:
        try:
            entry = self._resolve_hud_model_entry()
            from backend.inference.reasoning import reasoning_control_available

            visible = reasoning_control_available(entry)
            hud_bar.query_one('#hud-reasoning').display = visible
            hud_bar.query_one('#hud-label-reasoning').display = visible
        except Exception:
            pass

    def _sync_hud_autonomy_visibility(self, hud_bar) -> None:
        try:
            current_mode = self._active_interaction_mode()
            is_agent = current_mode == AGENT_MODE
            hud_bar.query_one('#hud-autonomy').display = is_agent
            hud_bar.query_one('#hud-label-autonomy').display = is_agent
        except Exception:
            pass

    def _render_hud_bar(self) -> None:
        hud = self._hud
        raw_state = hud.state.agent_state_label or 'Ready'
        display_state, state_color = self._resolve_state_display(raw_state)
        display_state = self._append_turn_duration(display_state, raw_state)

        used = hud.state.context_tokens
        limit = hud.state.context_limit
        _, model_short = HUDBar.describe_model(hud.state.model)
        model_display = model_short if model_short != '(not set)' else '(not set)'
        autonomy = self._current_autonomy_level()
        hud.update_autonomy(autonomy)
        current_mode = self._active_interaction_mode()
        hud.update_interaction_mode(current_mode)

        workspace = self._resolve_workspace_display(hud.state.workspace_path)
        ws_display = HUDBar.compact_workspace_label(workspace, max_len=24)
        line1 = self._build_hud_line1(display_state, state_color, raw_state=raw_state)
        line2_leading = self._build_hud_line2_leading(ws_display)
        model_label = f'[{NAVY_TEXT_SECONDARY}]{model_display}[/]'

        token_display = self._build_context_display(used, limit)
        help_hint = r'[#54597b]\[[/][#eacb8a]F1[/][#54597b]][/] [#969aad]Help[/]'
        line2 = token_display

        hud_bar = self.query_one('#hud-bar', HUD)
        hud_bar.query_one('#hud-line-1', Label).update(line1)
        hud_bar.query_one('#hud-model-name', Label).update(model_label)
        hud_bar.query_one('#hud-line-2-ws', Label).update(line2_leading)
        hud_bar.query_one('#hud-line-2', Label).update(line2)
        hud_bar.query_one('#hud-line-1-help', Label).update(help_hint)
        self._sync_hud_reasoning_select(hud_bar)
        self._sync_hud_autonomy_select(hud_bar, autonomy)
        self._sync_hud_mode_select(hud_bar)
        self._sync_hud_autonomy_visibility(hud_bar)
        self._sync_hud_reasoning_visibility(hud_bar)

    def _update_input_identity(self, mode: str | None = None) -> None:
        """Update InputBar border title and hint based on mode."""
        if mode is None:
            mode = self._active_interaction_mode()
        mode = normalize_interaction_mode(mode)
        try:
            bar = self.query_one('#input-bar', InputBar)
            hint = self.query_one('#input-hint', Label)
            ta = self.query_one('#input', TextArea)
        except Exception:
            return
        if is_chat_mode(mode):
            bar.border_title = ' Chat '
            hint.update('Ask about the codebase or architecture...')
        elif mode == PLAN_MODE:
            bar.border_title = ' Plan '
            hint.update('Describe what Grinta should inspect and plan...')
        else:
            bar.border_title = ' Agent task '
            hint.update('Describe a task for Grinta to execute...')
        pending = len(getattr(self, '_pending_image_urls', []) or [])
        if pending > 0:
            refresh = getattr(self, '_refresh_input_attachment_hint', None)
            if callable(refresh):
                refresh()
            return
        hint.remove_class('-image-attached')
        hint.display = not bool(ta.text.strip())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lst = self.query_one('#suggestions-list', ListView)
        if lst.has_class('-hidden') or not self._suggestion_matches:
            return
        selected = lst.index if lst.index is not None else 0
        if 0 <= selected < len(self._suggestion_matches):
            self.apply_slash_command_from_palette(self._suggestion_matches[selected])

    def _refresh_runtime_feedback(self) -> None:
        self._tick_retry_countdown()
        if not self._is_unmounted:
            self._render_hud_bar()
            self._maybe_refresh_session_audit()

    def arm_retry_countdown(
        self,
        *,
        attempt: int,
        max_attempts: int,
        delay_seconds: float,
        reason: str = '',
        source: str = '',
    ) -> None:
        """Arm a live HUD countdown for an in-flight retry/backoff wait."""
        self._retry_countdown_attempt = max(1, int(attempt))
        self._retry_countdown_max_attempts = max(
            self._retry_countdown_attempt, int(max_attempts)
        )
        self._retry_countdown_reason = str(reason or 'transient failure').strip()
        self._retry_countdown_source = str(source or '').strip().lower()
        delay = max(0.0, float(delay_seconds))
        self._retry_countdown_deadline = time.monotonic() + delay

    def _clear_retry_countdown(self) -> None:
        self._retry_countdown_deadline = None

    def _tick_retry_countdown(self) -> None:
        deadline = getattr(self, '_retry_countdown_deadline', None)
        if deadline is None:
            return

        remaining = float(deadline) - time.monotonic()
        attempt = int(getattr(self, '_retry_countdown_attempt', 1) or 1)
        max_attempts = int(
            getattr(self, '_retry_countdown_max_attempts', attempt) or attempt
        )
        reason = str(
            getattr(self, '_retry_countdown_reason', '') or 'transient failure'
        )
        source = str(getattr(self, '_retry_countdown_source', '') or '')
        retry_target = 'provider stream' if source == 'llm_stream' else 'provider'

        if remaining > 0:
            delay_str = f'{int(remaining + 0.999)}s' if remaining >= 1 else '<1s'
            label = f'Backoff {attempt}/{max_attempts} (retrying in {delay_str})'
            meta = f'Waiting {delay_str} to retry after {reason}'
        else:
            label = f'Backoff {attempt}/{max_attempts} (retrying now)'
            meta = f'Resuming {retry_target} after {reason}'

        self._hud.update_agent_state(label)
        self._retry_summary = label
        self._retry_meta = meta
        self._retry_active = True

    def _maybe_refresh_session_audit(self) -> None:
        """Keep ``app.stripped.log`` / ``app.audit.txt`` current during long runs.

        Runs off the Textual event loop so parsing a growing ``app.log`` cannot
        freeze scroll/keyboard (session logs showed multi-second poll gaps
        aligned with synchronous audit writes).
        """
        if not getattr(self, '_agent_running', False):
            return
        if getattr(self, '_session_audit_in_flight', False):
            return
        from backend.core.constants import DEFAULT_SESSION_AUDIT_REFRESH_SECONDS

        now = time.monotonic()
        last = getattr(self, '_last_session_audit_refresh_at', 0.0)
        if (now - last) < DEFAULT_SESSION_AUDIT_REFRESH_SECONDS:
            return
        self._last_session_audit_refresh_at = now
        self._session_audit_in_flight = True

        def _run_audit() -> None:
            try:
                from backend.core.logging.logger import finalize_session_logging_audit

                finalize_session_logging_audit()
            except Exception:
                pass
            finally:
                self._session_audit_in_flight = False

        import threading

        threading.Thread(target=_run_audit, daemon=True, name='session-audit').start()

    def set_agent_phase(self, state_value: str) -> None:
        key = state_value.lower().strip()
        if key.startswith('agentstate.'):
            key = key[len('agentstate.') :]
        if '.' in key:
            key = key.split('.')[-1]
        if key.startswith('backoff'):
            label = 'Backoff'
        elif key.startswith('retrying'):
            label = 'Retrying'
        else:
            label = self._STATE_LABELS.get(key, state_value)
        if label != self._phase_label:
            self._phase_label = label
            self._phase_started_at = time.monotonic()
            self._render_hud_bar()

    def set_retry_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = True,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No retry activity'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._retry_summary = summary_text
        self._retry_meta = meta_text
        self._retry_active = active
        if not active:
            self._clear_retry_countdown()

    def clear_retry_status(self, meta: str = 'Idle') -> None:
        self._clear_retry_countdown()
        self.set_retry_status('No retry activity', meta=meta, active=False)

    def set_runtime_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = False,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No runtime notices'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._runtime_summary = summary_text
        self._runtime_meta = meta_text
        self._runtime_active = active

    def clear_runtime_status(self, meta: str = 'Idle') -> None:
        self.set_runtime_status('No runtime notices', meta=meta, active=False)

    def set_worker_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = False,
        has_error: bool = False,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No delegated work'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._worker_summary = summary_text
        self._worker_meta = meta_text
        self._worker_active = active
        self._worker_has_error = has_error

    def _resolve_subcommand_hint(
        self,
        cmd: str,
        parts: list[str],
    ) -> str | None:
        if cmd == '/sessions' and len(parts) > 1 and parts[-1].startswith('--'):
            return 'Sessions flags: --limit --search --sort --preview --delete'
        if cmd == '/help' and len(parts) > 1 and parts[-1].startswith('--'):
            return 'Help flags: --all or --search <term>'
        return None

    def _resolve_slash_hint(self, parts: list[str]) -> str:
        cmd = parts[0].lower()
        if cmd not in self._SLASH_HINTS:
            candidates = [c for c in self._SLASH_HINTS if c.startswith(cmd)]
            if candidates:
                return 'Commands: ' + ', '.join(candidates[:5])
            return 'Commands: /help, /clear, /settings, /sessions, /resume, /quit'
        sub_hint = self._resolve_subcommand_hint(cmd, parts)
        if sub_hint is not None:
            return sub_hint
        return self._SLASH_HINTS[cmd]

    def _parse_slash_command(self, stripped: str) -> str:
        try:
            parts = shlex.split(stripped)
        except ValueError:
            return 'Command syntax error: check quotes.'
        if not parts:
            return ''
        return self._resolve_slash_hint(parts)

    def _update_command_hint(self, text: str) -> None:
        stripped = _strip_ansi(text).strip()
        if not stripped.startswith('/'):
            if self._command_hint:
                self._command_hint = ''
                self._render_hud_bar()
            return

        hint = self._parse_slash_command(stripped)

        if hint != self._command_hint:
            self._command_hint = hint
            self._render_hud_bar()

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or 'Ready')
        self._render_hud_bar()
