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

from backend.cli.hud import HUDBar
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_GREEN_ACCENT,
    NAVY_RED_ACCENT,
    NAVY_TEXT_DIM,
    NAVY_TEXT_SECONDARY,
    NAVY_YELLOW_ACCENT,
)
from backend.cli.tui._app_helpers import (
    _strip_ansi,
)
from backend.cli.tui._app_small_widgets import (
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
)


class _AppScreenStateMixin:
    """State-related methods of GrintaScreen."""

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
        name = getattr(self._config, 'default_agent', None)
        return name.strip() if isinstance(name, str) and name.strip() else 'agent'

    def _active_agent_config(self) -> Any | None:
        getter = getattr(self._config, 'get_agent_config', None)
        if not callable(getter):
            return None
        try:
            return getter(self._active_agent_name())
        except TypeError:
            return getter()

    def _active_interaction_mode(self) -> str:
        agent_config = self._active_agent_config()
        return normalize_interaction_mode(
            getattr(agent_config, 'mode', AGENT_MODE),
            default=AGENT_MODE,
        )

    def _render_hud_bar(self) -> None:
        hud = self._hud
        raw_state = hud.state.agent_state_label or 'Ready'
        display_state, state_color = self._resolve_state_display(raw_state)

        used = hud.state.context_tokens
        limit = hud.state.context_limit
        # Restore Model and Autonomy
        _, model_short = HUDBar.describe_model(hud.state.model)
        model_display = model_short if model_short != '(not set)' else '(not set)'
        autonomy = hud.state.autonomy_level

        # Top line info
        workspace = str(hud.state.workspace_path or Path(os.getcwd()))
        try:
            home = str(Path.home())
            if workspace.startswith(home):
                workspace = workspace.replace(home, '~', 1)
        except Exception:
            pass
        line1_parts = []
        line1_parts.append('[#91abec bold]GRINTA[/]')
        line1_parts.append(f'[{state_color}]● {display_state}[/]')
        line1_parts.append(f'[{NAVY_TEXT_SECONDARY}]Model: {model_display}[/]')
        ws_display = HUDBar.ellipsize_path(workspace, 35)
        line1_parts.append(f'[{NAVY_TEXT_DIM}]Ws: {ws_display}[/]')
        line1 = '  '.join(line1_parts)

        # Context-window pressure with saturation percentage.
        if limit > 0:
            pct = min(100, used * 100 // limit)
            ctx_color = (
                NAVY_GREEN_ACCENT
                if pct < 80
                else NAVY_YELLOW_ACCENT
                if pct < 95
                else NAVY_RED_ACCENT
            )
            token_display = f'[{NAVY_TEXT_DIM}]Ctx: {used:,}/{limit:,} ({pct}%)  [{ctx_color}]●[/][/]'
        else:
            token_display = f'[{NAVY_TEXT_DIM}]Ctx: {used:,}[/]'

        help_hint = r'[#54597b]\[[/][#eacb8a bold]F1[/][#54597b]][/] [#969aad]Help[/]'
        line2 = f'{token_display}   {help_hint}'

        hud_bar = self.query_one('#hud-bar', HUD)
        hud_bar.query_one('#hud-line-1', Label).update(line1)
        hud_bar.query_one('#hud-line-2', Label).update(line2)
        try:
            autonomy_select = hud_bar.query_one('#hud-autonomy', Select)
            if autonomy_select.value != autonomy:
                autonomy_select.value = autonomy
        except Exception:
            pass
        try:
            mode_select = hud_bar.query_one('#hud-mode', Select)
            current_mode = self._active_interaction_mode()
            if current_mode not in VISIBLE_INTERACTION_MODES:
                current_mode = CHAT_MODE if is_chat_mode(current_mode) else AGENT_MODE
            if mode_select.value != current_mode:
                mode_select.value = current_mode
        except Exception:
            pass
        try:
            current_mode = self._active_interaction_mode()
            is_agent = current_mode == AGENT_MODE
            hud_bar.query_one('#hud-autonomy').display = is_agent
            hud_bar.query_one('#hud-label-autonomy').display = is_agent
        except Exception:
            pass

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
        hint.display = not bool(ta.text.strip())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lst = self.query_one('#suggestions-list', ListView)
        if lst.has_class('-hidden') or not self._suggestion_matches:
            return
        selected = lst.index if lst.index is not None else 0
        ta = self.query_one('#input', TextArea)
        if 0 <= selected < len(self._suggestion_matches):
            ta.text = self._suggestion_matches[selected] + ' '
        lst.add_class('-hidden')
        self._suggestion_matches = []
        ta.focus()

    def _refresh_runtime_feedback(self) -> None:
        if not self._is_unmounted:
            self._render_hud_bar()

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

    def set_current_operation(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = True,
    ) -> None:
        summary_text = re.sub(r'\s+', ' ', (summary or '').strip()) or 'Idle'
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip())
        if len(meta_text) > 140:
            meta_text = meta_text[:137] + '...'
        self._current_operation_summary = summary_text
        self._current_operation_meta = meta_text or 'Waiting for activity'
        self._current_operation_active = active

    def clear_current_operation(self, meta: str = 'Waiting for activity') -> None:
        self.set_current_operation('Idle', meta=meta, active=False)

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

    def clear_retry_status(self, meta: str = 'Idle') -> None:
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

    def _update_command_hint(self, text: str) -> None:
        stripped = _strip_ansi(text).strip()
        if not stripped.startswith('/'):
            if self._command_hint:
                self._command_hint = ''
                self._render_hud_bar()
            return

        try:
            parts = shlex.split(stripped)
        except ValueError:
            hint = 'Command syntax error: check quotes.'
        else:
            if not parts:
                hint = ''
            else:
                cmd = parts[0].lower()
                if cmd in self._SLASH_HINTS:
                    if (
                        cmd == '/sessions'
                        and len(parts) > 1
                        and parts[-1].startswith('--')
                    ):
                        hint = (
                            'Sessions flags: --limit --search --sort --preview --delete'
                        )
                    elif (
                        cmd == '/help' and len(parts) > 1 and parts[-1].startswith('--')
                    ):
                        hint = 'Help flags: --all or --search <term>'
                    else:
                        hint = self._SLASH_HINTS[cmd]
                else:
                    candidates = [c for c in self._SLASH_HINTS if c.startswith(cmd)]
                    hint = (
                        'Commands: ' + ', '.join(candidates[:5])
                        if candidates
                        else 'Commands: /help, /clear, /settings, /sessions, /resume, /quit'
                    )

        if hint != self._command_hint:
            self._command_hint = hint
            self._render_hud_bar()

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or 'Ready')
        self._render_hud_bar()
