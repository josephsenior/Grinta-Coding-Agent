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
from backend.cli.event_rendering.unified_renderer import (
    ActivityCard,
    ActivityRenderer,
)
from backend.cli.orient_tools import OrientLineModel


class RendererDisplayMixin:
    """history refresh, display writes, retry/runtime strips, cards."""

    _playbook_skills_cache: list[str] | None = None
    _playbook_skills_cache_mtime: float = 0.0

    def _register_widget_event_id(self, widget: Any) -> None:
        event_id = getattr(self, '_current_event_id', -1)
        if event_id < 0:
            return
        setattr(widget, '_ledger_event_id', event_id)
        cache = getattr(self, '_render_cache', None)
        if cache is not None:
            from backend.cli.tui.renderer.prep import RenderArtifact

            cache[event_id] = RenderArtifact(event_id, widget, measured_height=1)

    def clear_history(self) -> None:
        self._live_thinking_widget = None
        self._live_response_widget = None
        self._terminal_cards_by_session = {}
        self._terminal_commands_by_session = {}
        self._pending_terminal_command = None
        self._pending_terminal_card = None
        self._pending_shell_cards_by_command = defaultdict(deque)
        self._pending_file_read_cards_by_path = defaultdict(deque)
        self._pending_file_create_cards_by_path = defaultdict(deque)
        self._orient_burst_lines = []
        self._orient_burst_widgets = []
        self._orient_burst_area = 'codebase'
        self._active_worker_tasks = []
        self._worker_recent_results.clear()
        self._worker_completed = 0
        self._worker_failed = 0
        self._compaction_transcript_active = False
        self._history = []
        self._history_items_dropped = 0
        self._live_thinking = ''
        self._live_thinking_dirty = False
        self._live_response = ''
        self._live_response_dirty = False
        self._last_thinking_text_hash = ''
        self._last_thinking_artifact_hash = ''
        self._min_rendered_event_id = -1
        self._max_rendered_event_id = -1
        self._render_cache = {}
        self._render_prep_cache = {}
        self._mounted_event_ids = set()
        self._event_order = []
        self._last_task_sidebar_signature = None
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
        mcp_count = self._hud.state.mcp_servers
        skill_count = self._hud.bundled_skill_count

        mcp_servers = self._resolve_mcp_server_list(mcp_count)

        mcp_items = self._build_mcp_sidebar_items(mcp_servers)
        skill_items = self._build_skills_sidebar_items()
        mcp_loading = self._mcp_sidebar_is_loading(mcp_items)
        skills_loading = self._skills_sidebar_is_loading(skill_items)
        current_state = (mcp_servers, skill_count, mcp_loading, skills_loading)
        if current_state != self._last_sidebar_state:
            self._update_sidebar_section(
                '#sidebar-mcp',
                'MCP Servers'
                if mcp_loading
                else f'MCP Servers ({len(mcp_servers) if mcp_servers else 0})',
                mcp_items,
                empty_message=(
                    'Loading MCP servers...'
                    if mcp_loading
                    else 'No MCP servers configured'
                ),
            )
            self._update_sidebar_section(
                '#sidebar-skills',
                'Skills' if skills_loading else f'Skills ({len(skill_items)})',
                skill_items,
                empty_message=(
                    'Loading skills...' if skills_loading else 'No skills available'
                ),
            )

            self._last_sidebar_state = current_state

    def schedule_lsp_detection(self) -> None:
        """Probe installed language servers off the UI thread."""
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
        languages: set[str] = set()
        for _name, tool in cache.items():
            if tool.available:
                languages.add(tool.spec.language)
        return tuple(sorted(languages))

    def _refresh_lsp_sidebar(self) -> None:
        from textual.widgets import Static

        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        signature = self._lsp_sidebar_signature()
        if signature == getattr(self, '_last_lsp_sidebar_signature', None):
            return
        self._last_lsp_sidebar_signature = signature

        try:
            section = self._tui.query_one('#sidebar-lsp', CollapsibleSection)
        except Exception:
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
        if items:
            section.set_items(items)
        else:
            section.set_content('No language servers detected on PATH')

    def _build_lsp_sidebar_items(self, servers: dict[str, Any]) -> list[tuple]:
        seen_languages: set[str] = set()
        items: list[tuple] = []
        for _name, tool in sorted(
            servers.items(),
            key=lambda pair: (not pair[1].available, pair[1].spec.language, pair[0]),
        ):
            if not tool.available:
                continue
            language = tool.spec.language
            if language in seen_languages:
                continue
            seen_languages.add(language)
            items.append((language, f'lsp:{language}', False, 'ok', None, False))
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

        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        signature = self._dap_sidebar_signature()
        if signature == getattr(self, '_last_dap_sidebar_signature', None):
            return
        self._last_dap_sidebar_signature = signature

        try:
            section = self._tui.query_one('#sidebar-dap', CollapsibleSection)
        except Exception:
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
        if items:
            section.set_items(items)
        else:
            section.set_content('No debug adapters detected on PATH')

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
            items.append((language, f'dap:{language}', False, status, adapter, False))
        return items

    def _refresh_tasks_sidebar(self) -> None:
        """Keep task rows live even while transcript streaming is throttled."""
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        task_signature = task_panel_signature(self._task_list)
        signature_key = tuple(task_signature)
        if signature_key == getattr(self, '_last_task_sidebar_signature', None):
            return
        self._last_task_sidebar_signature = signature_key

        task_items = self._build_task_sidebar_items(task_signature)
        self._update_sidebar_section(
            '#sidebar-tasks',
            f'Tasks ({len(task_signature)})',
            task_items,
        )

        active_task_id: str | None = None
        for task_id, status, _desc in task_signature:
            if status == 'in_progress':
                active_task_id = task_id
                break

        try:
            section = self._tui.query_one('#sidebar-tasks', CollapsibleSection)
            if active_task_id:
                section.expand()
            for row in section.query(SidebarRow):
                if active_task_id and row.item_id == f'task:{active_task_id}':
                    row.add_class('-active-task')
                else:
                    row.remove_class('-active-task')
        except Exception:
            pass

    def _is_runtime_bootstrap_pending(self) -> bool:
        bootstrapping = getattr(self._tui, '_bootstrapping', None)
        if bootstrapping is None:
            return False
        return not bootstrapping.is_set()

    def _mcp_sidebar_is_loading(self, mcp_items: list) -> bool:
        if mcp_items:
            return False
        if self._hud.state.mcp_servers is None:
            return True
        return self._is_runtime_bootstrap_pending()

    def _skills_sidebar_is_loading(self, skill_items: list) -> bool:
        if skill_items:
            return False
        return self._is_runtime_bootstrap_pending()

    def _update_sidebar_section(
        self,
        widget_id,
        title,
        items,
        *,
        empty_message: str | None = None,
    ):
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        try:
            widget = self._tui.query_one(widget_id, CollapsibleSection)
            widget.set_title(title)
            if empty_message is not None:
                widget._content = empty_message
            widget.set_items(items)
        except Exception:
            pass

    def _build_task_sidebar_items(self, task_signature):
        _TASK_TO_SIDEBAR_STATUS = {
            'done': 'ok',
            'in_progress': 'running',
            'blocked': 'err',
            'todo': 'neutral',
            'skipped': 'warn',
        }
        task_items = []
        for task_id, status, desc in task_signature:
            item_status = _TASK_TO_SIDEBAR_STATUS.get(status, 'neutral')
            meta = task_id if task_id and task_id != '?' else None
            task_items.append((desc, f'task:{task_id}', False, item_status, meta))
        return task_items

    def _build_mcp_sidebar_items(self, mcp_servers):
        mcp_items = []
        if mcp_servers:
            for server in mcp_servers:
                name = server.get('name', 'unknown')
                server_type = server.get('type', 'stdio')
                mcp_items.append((name, f'mcp:{name}', True, 'info', server_type))
        return mcp_items

    def _build_skills_sidebar_items(self):
        from pathlib import Path

        import backend
        from backend.cli.event_rendering.sidebar import _load_playbook_skills

        skills_list: list[str] = []
        playbook_dir = Path(backend.__file__).resolve().parent / 'playbooks'
        try:
            mtime = playbook_dir.stat().st_mtime
        except OSError:
            mtime = 0.0
        if (
            self._playbook_skills_cache is not None
            and mtime == self._playbook_skills_cache_mtime
        ):
            skills_list = list(self._playbook_skills_cache)
        else:
            skills_list = _load_playbook_skills()
            self._playbook_skills_cache = list(skills_list)
            self._playbook_skills_cache_mtime = mtime
        skill_items = []
        if skills_list:
            for skill in sorted(skills_list):
                skill_items.append((skill, f'skill:{skill}', True, 'neutral', None))
        return skill_items

    def _resolve_mcp_server_list(self, mcp_count):
        from backend.integrations.mcp.native_backends import is_user_visible_mcp_server

        mcp_servers = None
        if (
            self._tui._config
            and getattr(self._tui._config, 'mcp', None)
            and getattr(self._tui._config.mcp, 'servers', None)
        ):
            mcp_servers = [
                {'name': s.name, 'type': s.type}
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

    def _deactivate_last_streaming_card(self, *, except_widget: Any = None) -> None:
        """Collapse the previous streaming card when a new action starts."""
        prev = getattr(self, '_last_streaming_card', None)
        if prev is None or prev is except_widget:
            return
        try:
            prev.set_processing(False)
            if not getattr(prev, 'is_pinned', False):
                prev.collapse()
        except Exception:
            pass
        self._last_streaming_card = None

    def _activate_activity_card(self, widget: Any) -> None:
        """Mark a card as the current streaming target and expand it."""
        if widget is None:
            return
        self._deactivate_last_streaming_card(except_widget=widget)
        self._last_streaming_card = widget
        self._last_active_card = widget
        try:
            widget.set_processing(True)
            if getattr(widget, 'should_auto_expand', lambda: False)():
                widget.expand()
        except Exception:
            pass

    def _clear_last_active_card_processing(self) -> None:
        """Clear the pulsing processing indicator on the last active card."""
        prev = getattr(self, '_last_active_card', None)
        if prev:
            try:
                prev.set_processing(False)
            except Exception:
                pass
            self._last_active_card = None
        clear_current_operation = getattr(self._tui, 'clear_current_operation', None)
        if callable(clear_current_operation):
            clear_current_operation()

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

    def _write_card(
        self,
        card: ActivityCard,
        *,
        collapsed: bool | None = None,
    ) -> Any:
        """Write an activity card to the transcript using native ActivityCard widget.

        ``collapsed`` defaults to compact so expandable tool cards never open
        unsolicited. Callers may still opt into an expanded state explicitly.
        """
        if collapsed is None:
            collapsed = True
        self._flush_orient_burst()
        self.commit_live_thinking()
        self._clear_last_active_card_processing()

        extra_content = ActivityRenderer.format_extra_lines(card.extra_lines)

        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        status_map = {
            'ok': 'ok',
            'err': 'err',
            'warn': 'warn',
            'neutral': 'neutral',
        }
        status = status_map.get(card.secondary_kind, 'neutral')
        terminal_command = None
        shell_kind = None
        if card.badge_category in ('shell', 'terminal', 'debugger'):
            from backend.cli.tui.helpers import infer_display_shell_kind

            terminal_command = TUIActivityCard._command_from_detail(card.detail)
            shell_kind = (
                'terminal'
                if card.badge_category == 'terminal'
                else 'debugger'
                if card.badge_category == 'debugger'
                else infer_display_shell_kind(terminal_command)
            )
        widget = TUIActivityCard(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            status=status,
            outcome=card.secondary,
            extra_content=extra_content,
            collapsed=collapsed,
            collapsible=card.is_collapsible,
            syntax_language=card.syntax_language,
            show_meta=bool(card.meta_lines),
            shell_kind=shell_kind,
            terminal_command=terminal_command,
        )
        if card.meta_lines:
            widget.set_meta(*card.meta_lines)

        is_tool = card.badge_category in (
            'tool',
            'shell',
            'terminal',
            'files',
            'browser',
            'mcp',
            'workers',
            'code',
            'debugger',
        )
        is_active = is_tool and card.secondary_kind == 'neutral'
        if is_active:
            self._activate_activity_card(widget)
            self._tui.set_current_operation(
                f'{card.verb} {card.detail}'.strip(),
                meta=card.secondary or 'Running',
                active=True,
            )
        else:
            if self._last_active_card is widget:
                self._last_active_card = None
            self._tui.set_current_operation(
                f'{card.verb} {card.detail}'.strip(),
                meta=card.secondary or 'Completed',
                active=False,
            )

        display = self._tui._get_display()
        self._register_widget_event_id(widget)
        if getattr(self, '_prepend_mode', False):
            display.prepend_widget(widget)
        else:
            display.append_widget(widget)
        self._sync_transcript_viewport()
        return widget

    def _append_transcript_widget(self, widget: Any) -> None:
        display = self._tui._get_display()
        self._register_widget_event_id(widget)
        if getattr(self, '_prepend_mode', False):
            display.prepend_widget(widget)
        else:
            display.append_widget(widget)
        self._sync_transcript_viewport()

    def _write_orient_line(self, model: OrientLineModel) -> Any:
        from backend.cli.tui.widgets.activity_card import OrientLine

        self.commit_live_thinking()
        self._clear_last_active_card_processing()
        widget = OrientLine(model)
        self._append_transcript_widget(widget)
        self._tui.set_current_operation(
            f'{model.verb} {model.target}'.strip(),
            meta=model.result,
            active=False,
        )
        return widget

    def _flush_orient_burst(self) -> None:
        """No-op — orient lines stay as individual transcript rows."""
        self._orient_burst_lines = []
        self._orient_burst_widgets = []
        self._orient_burst_area = 'codebase'

    def _apply_card_final_state(
        self,
        widget: Any,
        *,
        status: str,
        outcome: str | None,
        extra_content: str | None,
        collapse: bool,
        syntax_language: str | None,
        meta_lines: list[str] | None = None,
        diff_encoded: bool | None = None,
    ) -> None:
        try:
            widget.set_processing(False)
        except Exception:
            pass
        try:
            widget.set_status(status, outcome=outcome)
        except Exception:
            pass
        if syntax_language is not None:
            try:
                widget.set_syntax_language(syntax_language)
            except Exception:
                pass
        if extra_content is not None:
            try:
                widget.update_content(extra_content)
            except Exception:
                pass
        if diff_encoded is not None:
            try:
                widget.set_diff_encoded(diff_encoded)
            except Exception:
                pass
        if meta_lines:
            try:
                widget.set_meta(*meta_lines)
            except Exception:
                pass
        if status in {'err', 'warn'}:
            try:
                widget.expand()
            except Exception:
                pass
        if collapse and status not in {'err', 'warn'}:
            try:
                if not getattr(widget, 'is_pinned', False):
                    widget.collapse()
            except Exception:
                pass

    def _update_activity_card_outcome(
        self,
        widget: Any,
        *,
        status: str,
        outcome: str | None = None,
        extra_content: str | None = None,
        collapse: bool = False,
        operation_label: str | None = None,
        syntax_language: str | None = None,
        meta_lines: list[str] | None = None,
        diff_encoded: bool | None = None,
    ) -> None:
        """Update an in-flight activity card to its final state in-place.

        Used to merge an action card with its observation card so the user only
        sees a single transition (e.g. ``• Analyzed`` → ``✓ Analyzed completed``)
        instead of two separate cards.
        """
        if widget is None:
            return
        if self._last_active_card is widget:
            self._last_active_card = None
        self._apply_card_final_state(
            widget,
            status=status,
            outcome=outcome,
            extra_content=extra_content,
            collapse=collapse,
            syntax_language=syntax_language,
            meta_lines=meta_lines,
            diff_encoded=diff_encoded,
        )
        if operation_label is not None:
            self._tui.set_current_operation(
                operation_label,
                meta=outcome or 'Completed',
                active=False,
            )

    def _write_tui_file_card(
        self,
        verb: str,
        detail: str,
        *,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        collapsed: bool = True,
    ) -> None:
        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        self._flush_orient_burst()
        self.commit_live_thinking()
        self._clear_last_active_card_processing()
        status_map = {'ok': 'ok', 'err': 'err', 'warn': 'warn', 'neutral': 'neutral'}
        status = status_map.get(secondary_kind, 'neutral')
        widget = TUIActivityCard(
            verb=verb,
            detail=detail,
            badge_category='files',
            status=status,
            outcome=secondary,
            extra_content=extra_content,
            collapsed=collapsed,
            collapsible=bool(extra_content),
            diff_encoded=bool(extra_content),
            syntax_language='diff' if extra_content else None,
        )
        self._tui.set_current_operation(
            f'{verb} {detail}'.strip(),
            meta=secondary or 'Completed',
            active=False,
        )
        display = self._tui._get_display()
        self._register_widget_event_id(widget)
        display.append_widget(widget)
        self._sync_transcript_viewport()

    def _sync_transcript_viewport(self) -> None:
        """Keep mounted transcript widgets within the viewport budget."""
        try:
            display = self._tui._get_display()
        except (AttributeError, NoMatches):
            return
        if type(display).__name__ == 'MagicMock':
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
