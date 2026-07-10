"""RendererDisplayMixin: history refresh, display writes, retry/runtime strips, cards."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from rich.console import (
    Group,
)
from rich.text import (
    Text,
)
from textual.css.query import (
    NoMatches,
)

from backend.cli.event_rendering.panels import (
    task_panel_signature,
)
from backend.cli.tool_display.orient_tools import OrientLineModel
from backend.cli.tui.constants import (
    _TUI_HISTORY_RENDER_LIMIT,
    _TUI_RENDER_CACHE_EVICT_BATCH,
    _TUI_RENDER_CACHE_MAX,
)
from backend.cli.tui.renderer.mixins.terminal import RendererTerminalMixin


class RendererDisplayMixin:
    """history refresh, display writes, retry/runtime strips, cards."""

    _playbook_skills_cache: list[str] | None = None
    _playbook_skills_cache_sig: tuple[float, float] | None = None
    _sidebar_section_cache: dict[str, Any] | None = None
    _cached_display_is_mock: bool | None = None

    def _display_is_mock(self) -> bool:
        cached = self._cached_display_is_mock
        if cached is not None:
            return cached
        try:
            display = self._tui._get_display()
            result = type(display).__name__ == 'MagicMock'
        except Exception:
            result = False
        self._cached_display_is_mock = result
        return result

    def _append_history_items(self, *items: Any) -> None:
        history = self._history
        for item in items:
            if history.maxlen is not None and len(history) >= history.maxlen:
                self._history_items_dropped += 1
            history.append(item)

    @staticmethod
    def _bound_event_id_cache(cache: dict[int, Any]) -> None:
        if len(cache) <= _TUI_RENDER_CACHE_MAX:
            return
        excess = len(cache) - (_TUI_RENDER_CACHE_MAX - _TUI_RENDER_CACHE_EVICT_BATCH)
        for key in sorted(cache.keys())[:excess]:
            cache.pop(key, None)

    def _get_sidebar_section(self, widget_id: str) -> Any | None:
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        cache = self._sidebar_section_cache
        if cache is None:
            cache = {}
            self._sidebar_section_cache = cache
        section = cache.get(widget_id)
        if section is not None:
            return section
        try:
            section = self._tui.query_one(widget_id, CollapsibleSection)
        except Exception:
            return None
        cache[widget_id] = section
        return section

    def _get_sidebar_container(self) -> Any | None:
        cache = self._sidebar_section_cache
        if cache is None:
            cache = {}
            self._sidebar_section_cache = cache
        container = cache.get('#sidebar-container')
        if container is not None:
            return container
        try:
            container = self._tui.query_one('#sidebar-container')
        except Exception:
            return None
        cache['#sidebar-container'] = container
        return container

    def _register_widget_event_id(self, widget: Any) -> None:
        event_id = getattr(self, '_current_event_id', -1)
        if event_id < 0:
            return
        # Tag the widget so the viewport pruner can release this event's render
        # state when the widget is unmounted. We deliberately do NOT retain the
        # widget object anywhere: holding detached widget trees across a long
        # conversation made GC pause time grow without bound, which starved the
        # Textual event loop (the progressive freeze symptom).
        setattr(widget, '_ledger_event_id', event_id)

    def _forget_event_state(self, event_id: int | None) -> None:
        """Drop all per-event render state so a pruned widget can be GC'd.

        Called by the transcript viewport when it unmounts an off-screen widget.
        Clearing the event id from ``_mounted_event_ids`` also lets the
        load-earlier replay path re-render the row if the user scrolls back up.
        """
        if event_id is None or event_id < 0:
            return
        cache = getattr(self, '_render_cache', None)
        if cache is not None:
            cache.pop(event_id, None)
        prep = getattr(self, '_render_prep_cache', None)
        if prep is not None:
            prep.pop(event_id, None)
        mounted = getattr(self, '_mounted_event_ids', None)
        if mounted is not None:
            mounted.discard(event_id)

    def clear_history(self) -> None:
        self._live_thinking_widget = None
        self._live_response_widget = None
        self._terminal_cards_by_session = {}
        self._terminal_commands_by_session = {}
        self._pending_terminal_command = None
        self._pending_terminal_card = None
        self._pending_shell_cards_by_command = defaultdict(deque)
        self._pending_file_read_cards_by_path = defaultdict(deque)
        self._pending_checkpoint_line = None
        self._pending_acceptance_criteria_card = None
        self._pending_memory_recall_line = None
        self._pending_memory_persist_line = None
        self._orient_burst_lines = []
        self._orient_burst_widgets = []
        self._orient_burst_area = 'codebase'
        self._active_worker_tasks = []
        self._worker_recent_results.clear()
        self._worker_completed = 0
        self._worker_failed = 0
        self._compaction_transcript_active = False
        self._pending_compaction_scan_card = None
        self._last_streamed_preamble_text = ''
        self._step_draft.reset()
        self._history = deque(maxlen=_TUI_HISTORY_RENDER_LIMIT)
        self._history_items_dropped = 0
        self._live_thinking = ''
        self._live_thinking_dirty = False
        self._live_response = ''
        self._live_response_dirty = False
        self._last_thinking_artifact_hash = ''
        self._min_rendered_event_id = -1
        self._max_rendered_event_id = -1
        self._render_cache = {}
        self._render_prep_cache = {}
        self._mounted_event_ids = set()
        self._event_order = []
        self._last_task_sidebar_signature = None
        self._sidebar_section_cache = None
        self._file_edit_actions_by_id: dict[int, Any] = {}
        RendererTerminalMixin._init_terminal_state(self)
        try:
            self._tui._get_display().clear()
        except (AttributeError, NoMatches):
            pass
        self._refresh_display()

    def _refresh_display(self, *, skip_sidebar: bool = False) -> None:
        """Refresh derived sidebar state; transcript writes are incremental."""
        self._refresh_tasks_sidebar()
        self._refresh_lsp_sidebar()
        self._refresh_dap_sidebar()
        if skip_sidebar:
            return
        mcp_enabled = self._sidebar_mcp_enabled()
        mcp_count = self._hud.state.mcp_servers

        if not mcp_enabled:
            skill_items = self._build_skills_sidebar_items()
            skills_loading = self._skills_sidebar_is_loading(skill_items)
            current_state = (
                (),
                tuple(item[0] for item in skill_items),
                False,
                skills_loading,
                False,
            )
            if current_state != self._last_sidebar_state:
                self._sync_mcp_sidebar_disabled()
                self._update_sidebar_section(
                    '#sidebar-skills',
                    'Skills' if skills_loading else f'Skills ({len(skill_items)})',
                    skill_items,
                    empty_message=(
                        'Loading skills...' if skills_loading else 'No custom skills'
                    ),
                )
                self._last_sidebar_state = current_state
            return

        mcp_servers = self._resolve_mcp_server_list(mcp_count)

        mcp_items = self._build_mcp_sidebar_items(mcp_servers)
        skill_items = self._build_skills_sidebar_items()
        mcp_loading = self._mcp_sidebar_is_loading(mcp_items)
        skills_loading = self._skills_sidebar_is_loading(skill_items)
        current_state = (
            tuple((s.get('name'), s.get('type')) for s in mcp_servers)
            if mcp_servers
            else (),
            tuple(item[0] for item in skill_items),
            mcp_loading,
            skills_loading,
            mcp_enabled,
        )
        if current_state != self._last_sidebar_state:
            self._update_sidebar_section(
                '#sidebar-mcp',
                'MCP Servers'
                if mcp_loading
                else f'MCP Servers ({len(mcp_servers) if mcp_servers else 0})',
                mcp_items,
                empty_message=(
                    'Loading MCP servers...' if mcp_loading else 'No servers configured'
                ),
            )
            self._sync_sidebar_feature_switch('#sidebar-mcp', True)
            self._update_sidebar_section(
                '#sidebar-skills',
                'Skills' if skills_loading else f'Skills ({len(skill_items)})',
                skill_items,
                empty_message=(
                    'Loading skills...' if skills_loading else 'No custom skills'
                ),
            )

            self._last_sidebar_state = current_state

    def invalidate_sidebar(self) -> None:
        """Force MCP/skills sidebar panels to rebuild on next refresh."""
        self._last_sidebar_state = None
        self._playbook_skills_cache = None
        self._playbook_skills_cache_sig = None

    def schedule_lsp_detection(self) -> None:
        """Probe installed language servers off the UI thread."""
        if not self._sidebar_lsp_enabled() and not self._sidebar_debugger_enabled():
            self._lsp_servers_cache = {}
            self._dap_adapters_cache = []
            self._lsp_detection_scheduled = False
            self._last_lsp_sidebar_signature = None
            self._last_dap_sidebar_signature = None
            self._refresh_lsp_sidebar()
            self._refresh_dap_sidebar()
            return
        if getattr(self, '_lsp_detection_scheduled', False):
            return
        self._lsp_detection_scheduled = True
        try:
            self._loop.create_task(
                self._detect_lsp_servers_async(),
                name='grinta-tui-lsp-detect',
            )
        except RuntimeError:
            self._lsp_detection_scheduled = False

    async def _detect_lsp_servers_async(self) -> None:
        import asyncio
        import os

        disable_lsp = os.getenv('GRINTA_DISABLE_LSP_DETECTION') == '1'
        disable_dap = os.getenv('GRINTA_DISABLE_DEBUGGER_DETECTION') == '1'
        if disable_lsp:
            self._lsp_servers_cache = {}
        if disable_dap:
            self._dap_adapters_cache = []

        try:
            from backend.utils.runtime_detect import (
                detect_debug_adapters_summary,
                detect_lsp_servers,
            )

            probes: list[tuple[str, Any]] = []
            if not disable_lsp:
                probes.append(('lsp', asyncio.to_thread(detect_lsp_servers)))
            if not disable_dap:
                probes.append(('dap', asyncio.to_thread(detect_debug_adapters_summary)))
            if probes:
                results = await asyncio.gather(*(coro for _, coro in probes))
                for (kind, _), result in zip(probes, results, strict=True):
                    if kind == 'lsp':
                        self._lsp_servers_cache = result
                    else:
                        self._dap_adapters_cache = result
        except Exception:
            if not disable_lsp and getattr(self, '_lsp_servers_cache', None) is None:
                self._lsp_servers_cache = {}
            if not disable_dap and getattr(self, '_dap_adapters_cache', None) is None:
                self._dap_adapters_cache = []
        self._last_lsp_sidebar_signature = None
        self._last_dap_sidebar_signature = None
        self._refresh_lsp_sidebar()
        self._refresh_dap_sidebar()

    def _lsp_sidebar_signature(self) -> tuple[Any, ...]:
        cache = getattr(self, '_lsp_servers_cache', None)
        if cache is None:
            return ('pending',)
        return tuple(sorted(name for name, tool in cache.items() if tool.available))

    def _refresh_lsp_sidebar(self) -> None:
        from textual.widgets import Static


        if not self._sidebar_lsp_enabled():
            signature = ('disabled',)
            if signature == getattr(self, '_last_lsp_sidebar_signature', None):
                return
            self._last_lsp_sidebar_signature = signature
            section = self._get_sidebar_section('#sidebar-lsp')
            if section is None:
                return
            section.set_title('LSP Servers')
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup('Disabled'))
            except Exception:
                section.set_content('Disabled')
            self._sync_sidebar_feature_switch('#sidebar-lsp', False)
            return

        signature = self._lsp_sidebar_signature()
        if signature == getattr(self, '_last_lsp_sidebar_signature', None):
            return
        self._last_lsp_sidebar_signature = signature

        section = self._get_sidebar_section('#sidebar-lsp')
        if section is None:
            return

        cache = getattr(self, '_lsp_servers_cache', None)
        if cache is None:
            section.set_title('LSP Servers')
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup('Scanning local PATH...'))
            except Exception:
                section.set_content('Scanning local PATH...')
            return

        items = self._build_lsp_sidebar_items(cache)
        available_count = len(items)
        title = (
            f'LSP Servers ({available_count})' if available_count else 'LSP Servers (0)'
        )
        section.set_title(title)
        self._sync_sidebar_feature_switch('#sidebar-lsp', True)
        if items:
            section.set_items(items)
        else:
            message = 'No language servers detected on PATH'
            section._content = message
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup(message))
            except Exception:
                section.set_content(message)

    def _build_lsp_sidebar_items(self, servers: dict[str, Any]) -> list[tuple]:
        from backend.utils.runtime_detect import CANONICAL_LSP_SERVERS

        items: list[tuple] = []
        for key, spec in sorted(CANONICAL_LSP_SERVERS.items()):
            tool = servers.get(spec.name)
            if tool is None or not tool.available:
                continue
            label = f'{key} ({spec.name})'
            items.append((label, f'lsp:{key}', False, 'ok', None, False))
        return items

    def _dap_sidebar_signature(self) -> tuple[Any, ...]:
        cache = getattr(self, '_dap_adapters_cache', None)
        if cache is None:
            return ('pending',)
        return tuple(
            sorted(
                (
                    entry.get('language'),
                    entry.get('adapter'),
                    bool(entry.get('available')),
                    bool(entry.get('auto_resolvable', entry.get('available'))),
                )
                for entry in cache
            )
        )

    def _refresh_dap_sidebar(self) -> None:
        from textual.widgets import Static


        if not self._sidebar_debugger_enabled():
            signature = ('disabled',)
            if signature == getattr(self, '_last_dap_sidebar_signature', None):
                return
            self._last_dap_sidebar_signature = signature
            section = self._get_sidebar_section('#sidebar-dap')
            if section is None:
                return
            section.set_title('Debug Adapters')
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup('Disabled'))
            except Exception:
                section.set_content('Disabled')
            self._sync_sidebar_feature_switch('#sidebar-dap', False)
            return

        signature = self._dap_sidebar_signature()
        if signature == getattr(self, '_last_dap_sidebar_signature', None):
            return
        self._last_dap_sidebar_signature = signature

        section = self._get_sidebar_section('#sidebar-dap')
        if section is None:
            return

        cache = getattr(self, '_dap_adapters_cache', None)
        if cache is None:
            section.set_title('Debug Adapters')
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup('Scanning local PATH...'))
            except Exception:
                section.set_content('Scanning local PATH...')
            return

        items = self._build_dap_sidebar_items(cache)
        available_count = len(items)
        title = (
            f'Debug Adapters ({available_count})'
            if available_count
            else 'Debug Adapters (0)'
        )
        section.set_title(title)
        self._sync_sidebar_feature_switch('#sidebar-dap', True)
        if items:
            section.set_items(items)
        else:
            message = 'No debug adapters detected on PATH'
            section._content = message
            try:
                empty = section.query_one('#empty-text', Static)
                empty.update(section._empty_markup(message))
            except Exception:
                section.set_content(message)

    def _build_dap_sidebar_items(self, adapters: list[dict[str, Any]]) -> list[tuple]:
        items: list[tuple] = []
        for entry in sorted(
            adapters,
            key=lambda row: (
                not row.get('available'),
                str(row.get('language') or ''),
                str(row.get('adapter') or ''),
            ),
        ):
            if not entry.get('available'):
                continue
            language = str(entry.get('language') or 'unknown')
            adapter = str(entry.get('adapter') or 'unknown')
            auto_resolvable = entry.get('auto_resolvable', entry.get('available'))
            status = 'ok' if auto_resolvable else 'warn'
            items.append((language, f'dap:{adapter}', False, status, None, False))
        return items

    def _refresh_tasks_sidebar(self) -> None:
        """Keep task rows live even while transcript streaming is throttled."""
        from backend.cli.tui.widgets.collapsible import SidebarRow
        from backend.core.tasks.task_status import TASK_STATUS_DONE

        task_signature = task_panel_signature(self._task_list)
        signature_key = tuple(task_signature)
        if signature_key == getattr(self, '_last_task_sidebar_signature', None):
            return

        task_items = self._build_task_sidebar_items(task_signature)
        total = len(task_signature)
        done = sum(
            1 for _tid, status, _desc in task_signature if status == TASK_STATUS_DONE
        )
        if total == 0:
            title = 'Tasks'
        elif done >= total:
            title = f'Tasks · {done}/{total} done'
        else:
            title = f'Tasks · {done}/{total} done'
        if not self._update_sidebar_section(
            '#sidebar-tasks',
            title,
            task_items,
        ):
            return
        self._last_task_sidebar_signature = signature_key

        active_task_id: str | None = None
        for task_id, status, _desc in task_signature:
            if status == 'in_progress':
                active_task_id = task_id
                break

        try:
            section = self._get_sidebar_section('#sidebar-tasks')
            if section is None:
                return
            if active_task_id:
                section.expand()
            for row in section.query(SidebarRow):
                if active_task_id and row.item_id == f'task:{active_task_id}':
                    row.add_class('-active-task')
                else:
                    row.remove_class('-active-task')
            self._schedule_tasks_sidebar_relayout(section)
        except Exception:
            pass

    def _schedule_tasks_sidebar_relayout(self, section: Any) -> None:
        """Second-pass layout after dynamic task rows mount."""
        call_after = getattr(self._tui, 'call_after_refresh', None)
        if not callable(call_after):
            section.refresh(layout=True)
            return

        def _relayout() -> None:
            try:
                section.refresh(layout=True)
                container = self._get_sidebar_container()
                if container is not None:
                    container.refresh(layout=True)
            except Exception:
                pass

        call_after(_relayout)

    def _is_environment_probe_pending(self) -> bool:
        ready = getattr(self._tui, '_environment_ready', None)
        if ready is None:
            return False
        return not ready.is_set()

    def _is_runtime_bootstrap_pending(self) -> bool:
        bootstrapping = getattr(self._tui, '_bootstrapping', None)
        if bootstrapping is None:
            return False
        return not bootstrapping.is_set()

    def _mcp_sidebar_is_loading(self, mcp_items: list) -> bool:
        if mcp_items:
            return False
        return self._is_environment_probe_pending()

    def _skills_sidebar_is_loading(self, skill_items: list) -> bool:
        if skill_items:
            return False
        return self._is_runtime_bootstrap_pending()

    def _sync_mcp_sidebar_disabled(self) -> None:
        """Show the same muted ``● Disabled`` empty state as LSP/DAP."""
        section = self._get_sidebar_section('#sidebar-mcp')
        if section is None:
            return
        section.set_title('MCP Servers')
        section.set_content('Disabled')
        self._sync_sidebar_feature_switch('#sidebar-mcp', False)

    def _update_sidebar_section(
        self,
        widget_id,
        title,
        items,
        *,
        empty_message: str | None = None,
    ) -> bool:

        widget = self._get_sidebar_section(widget_id)
        if widget is None:
            return False
        try:
            widget.set_title(title)
            if empty_message is not None:
                widget._content = empty_message
            widget.set_items(items)
            return True
        except Exception:
            return False

    def _sync_sidebar_feature_switch(self, widget_id: str, enabled: bool) -> None:

        section = self._get_sidebar_section(widget_id)
        if section is None:
            return
        try:
            section.set_feature_enabled(enabled)
        except Exception:
            pass

    def _sidebar_mcp_enabled(self) -> bool:
        mcp = getattr(getattr(self._tui, '_config', None), 'mcp', None)
        return bool(getattr(mcp, 'enabled', False))

    def _sidebar_lsp_enabled(self) -> bool:
        from backend.core.constants import DEFAULT_AGENT_LSP_QUERY_ENABLED

        getter = getattr(self._tui, '_active_agent_config', None)
        agent_config = getter() if callable(getter) else None
        if agent_config is None:
            return DEFAULT_AGENT_LSP_QUERY_ENABLED
        return bool(
            getattr(agent_config, 'enable_lsp_query', DEFAULT_AGENT_LSP_QUERY_ENABLED)
        )

    def _sidebar_debugger_enabled(self) -> bool:
        from backend.core.constants import DEFAULT_AGENT_DEBUGGER_ENABLED

        getter = getattr(self._tui, '_active_agent_config', None)
        agent_config = getter() if callable(getter) else None
        if agent_config is None:
            return DEFAULT_AGENT_DEBUGGER_ENABLED
        return bool(
            getattr(agent_config, 'enable_debugger', DEFAULT_AGENT_DEBUGGER_ENABLED)
        )

    def _build_task_sidebar_items(self, task_signature):
        # Map task-tracker statuses to sidebar status keys. The sidebar uses
        # the canonical 'todo' / 'in_progress' / 'done' / 'skipped' / 'blocked'
        # names directly so the SidebarRow can pick up the matching
        # TASK_STATUS_PLAN_ICONS glyph (text-readable, not just color).
        task_items = []
        for index, (task_id, status, desc) in enumerate(task_signature, start=1):
            task_items.append(
                (
                    desc,
                    f'task:{task_id}',
                    False,
                    status,
                    None,
                    True,
                    {'prefix': f'{index}.'},
                )
            )
        return task_items

    def _build_mcp_sidebar_items(self, mcp_servers):
        mcp_items = []
        if mcp_servers:
            for server in mcp_servers:
                name = server.get('name', 'unknown')
                enabled = bool(server.get('enabled', True))
                status = 'ok' if enabled else 'neutral'
                options = {'toggleable': True, 'disabled': not enabled}
                mcp_items.append(
                    (name, f'mcp:{name}', False, status, None, False, options)
                )
        return mcp_items

    def _skills_dirs_mtime(self) -> tuple[float, float]:
        from pathlib import Path

        import backend

        playbook_dir = Path(backend.__file__).resolve().parent / 'playbooks'
        user_dir = Path.home() / '.grinta' / 'skills'
        try:
            playbook_mtime = playbook_dir.stat().st_mtime
        except OSError:
            playbook_mtime = 0.0
        try:
            user_mtime = user_dir.stat().st_mtime
        except OSError:
            user_mtime = 0.0
        return playbook_mtime, user_mtime

    def _build_skills_sidebar_items(self):
        from backend.cli.event_rendering import sidebar as sidebar_module

        sig = self._skills_dirs_mtime()
        if (
            self._playbook_skills_cache is not None
            and sig == self._playbook_skills_cache_sig
        ):
            return list(self._playbook_skills_cache)
        items = sidebar_module.load_sidebar_skill_items()
        self._playbook_skills_cache = list(items)
        self._playbook_skills_cache_sig = sig
        return items

    def _resolve_mcp_server_list(self, mcp_count):
        from backend.integrations.mcp.native_backends import is_user_visible_mcp_server

        mcp_servers = None
        if (
            self._tui._config
            and getattr(self._tui._config, 'mcp', None)
            and getattr(self._tui._config.mcp, 'servers', None)
        ):
            mcp_servers = [
                {
                    'name': s.name,
                    'type': s.type,
                    'enabled': bool(getattr(s, 'enabled', True)),
                }
                for s in self._tui._config.mcp.servers
                if is_user_visible_mcp_server(s.name)
            ]

        if not mcp_servers and mcp_count:
            mcp_servers = [
                {'name': f'MCP Server {i + 1}', 'type': 'active'}
                for i in range(mcp_count)
            ]
        return mcp_servers

    def _write_lines(self, lines: list[Any]) -> None:
        items = []
        for line in lines:
            if isinstance(line, str):
                items.append(Text.from_markup(line))
            else:
                items.append(line)
        self.add_to_history(Group(*items))

    def _update_retry_strip(self, summary: str, meta: str) -> None:
        self._tui.set_retry_status(summary, meta=meta, active=True)

    def _clear_retry_strip(self, meta: str = 'Idle') -> None:
        self._tui.clear_retry_status(meta=meta)

    def _update_runtime_strip(
        self, summary: str, meta: str, *, active: bool = False
    ) -> None:
        self._tui.set_runtime_status(summary, meta=meta, active=active)

    def _clear_runtime_strip(self, meta: str = 'Idle') -> None:
        self._tui.clear_runtime_status(meta=meta)

    @staticmethod
    def _summarize_worker_task(task: str) -> str:
        compact = re.sub(r'\s+', ' ', (task or '').strip())
        if not compact:
            return 'delegated task'
        return compact[:72] + ('...' if len(compact) > 72 else '')

    def _sync_worker_strip(self) -> None:
        active = len(self._active_worker_tasks)
        if active:
            summary = f'{active} worker{"s" if active != 1 else ""} active'
            meta_parts = [
                ' | '.join(self._active_worker_tasks[:2]),
                f'done {self._worker_completed}',
            ]
            if self._worker_failed:
                meta_parts.append(f'failed {self._worker_failed}')
            self._tui.set_worker_status(
                summary,
                meta='  •  '.join(part for part in meta_parts if part),
                active=True,
                has_error=self._worker_failed > 0,
            )
            return

        if self._worker_completed or self._worker_failed:
            summary = 'Workers idle'
            meta_parts = [f'done {self._worker_completed}']
            if self._worker_failed:
                meta_parts.append(f'failed {self._worker_failed}')
            if self._worker_recent_results:
                meta_parts.append('latest: ' + ' | '.join(self._worker_recent_results))
            self._tui.set_worker_status(
                summary,
                meta='  •  '.join(meta_parts),
                active=False,
                has_error=self._worker_failed > 0,
            )
            return

        self._tui.set_worker_status(
            'No delegated work', meta='Idle', active=False, has_error=False
        )

    def _append_transcript_widget(self, widget: Any) -> None:
        display = self._tui._get_display()
        self._register_widget_event_id(widget)
        if getattr(self, '_prepend_mode', False):
            display.prepend_widget(widget)
        else:
            display.append_widget(widget)
        self._sync_transcript_viewport()

    def _append_scan_line_card(self, card: Any) -> Any:
        """Append a 1-line :class:`ScanLineCard` to the transcript feed."""
        self._flush_orient_burst()
        self.commit_live_thinking()
        self._register_widget_event_id(card)
        display = self._tui._get_display()
        display.append_widget(card)
        self._sync_transcript_viewport()
        return card

    def _write_orient_line(self, model: OrientLineModel) -> Any:
        from backend.cli.tui.widgets.activity_card import OrientLine

        self.commit_live_thinking()
        widget = OrientLine(model)
        self._append_transcript_widget(widget)
        return widget

    def _flush_orient_burst(self) -> None:
        """No-op — orient lines stay as individual transcript rows."""
        self._orient_burst_lines = []
        self._orient_burst_widgets = []
        self._orient_burst_area = 'codebase'

    def _sync_transcript_viewport(self) -> None:
        """Keep mounted transcript widgets within the viewport budget."""
        try:
            display = self._tui._get_display()
        except (AttributeError, NoMatches):
            return
        if self._display_is_mock():
            return
        sync = getattr(display, 'sync_viewport', None)
        if callable(sync):
            sync(self)
            return
        self._maybe_prune_transcript_legacy()

    def _maybe_prune_transcript_legacy(self) -> None:
        """Legacy prune path for mocks/tests without viewport support."""
        try:
            display = self._tui._get_display()
        except (AttributeError, NoMatches):
            return
        if not hasattr(display, 'child_widget_count'):
            return
        if not hasattr(display, '_VIEWPORT_MAX_MOUNTED'):
            return
        threshold = display._VIEWPORT_MAX_MOUNTED
        if display.child_widget_count <= threshold:
            return
        overflow = display.child_widget_count - threshold
        display.prune_oldest(overflow)
