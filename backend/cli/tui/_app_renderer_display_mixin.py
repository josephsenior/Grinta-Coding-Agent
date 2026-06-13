"""_AppRendererDisplayMixin: history refresh, display writes, retry/runtime strips, cards."""

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

from backend.cli._event_renderer.panels import (
    task_panel_signature,
)
from backend.cli._event_renderer.unified_renderer import (
    ActivityCard,
)


class _AppRendererDisplayMixin:
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
            from backend.cli.tui._render_prep import RenderArtifact

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
        if skip_sidebar:
            return
        mcp_count = self._hud.state.mcp_servers
        skill_count = self._hud.bundled_skill_count

        mcp_servers = self._resolve_mcp_server_list(mcp_count)

        current_state = (mcp_servers, skill_count)
        if current_state != self._last_sidebar_state:
            mcp_items = self._build_mcp_sidebar_items(mcp_servers)
            skill_items = self._build_skills_sidebar_items()

            self._update_sidebar_section(
                '#sidebar-mcp',
                f'MCP Servers ({len(mcp_servers) if mcp_servers else 0})',
                mcp_items,
            )
            self._update_sidebar_section(
                '#sidebar-skills',
                f'Skills ({len(skill_items)})',
                skill_items,
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

        if os.getenv('GRINTA_DISABLE_LSP_DETECTION') == '1':
            self._lsp_servers_cache = {}
            self._last_lsp_sidebar_signature = None
            self._refresh_lsp_sidebar()
            return

        try:
            from backend.utils.runtime_detect import detect_lsp_servers

            self._lsp_servers_cache = await asyncio.to_thread(detect_lsp_servers)
        except Exception:
            self._lsp_servers_cache = {}
        self._last_lsp_sidebar_signature = None
        self._refresh_lsp_sidebar()

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
                empty.update('Scanning local PATH…')
            except Exception:
                section.set_content('Scanning local PATH…')
            return

        items = self._build_lsp_sidebar_items(cache)
        available_count = len(items)
        title = (
            f'LSP Servers ({available_count})'
            if available_count
            else 'LSP Servers (0)'
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

    def _update_sidebar_section(self, widget_id, title, items):
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        try:
            widget = self._tui.query_one(widget_id, CollapsibleSection)
            widget.set_title(title)
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
        from backend.cli._event_renderer.sidebar import _load_playbook_skills

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
        mcp_servers = None
        if (
            self._tui._config
            and getattr(self._tui._config, 'mcp', None)
            and getattr(self._tui._config.mcp, 'servers', None)
        ):
            mcp_servers = [
                {'name': s.name, 'type': s.type}
                for s in self._tui._config.mcp.servers
                if s.name != 'app-mcp'
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

    def _clear_last_active_card_processing(self) -> None:
        """Clear the pulsing processing indicator on the last active card."""
        if hasattr(self, '_last_active_card') and self._last_active_card:
            try:
                self._last_active_card.set_processing(False)
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
        self.commit_live_thinking()
        self._clear_last_active_card_processing()

        extra_content = None
        if card.extra_lines:
            extra_parts = []
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                extra_parts.append(f'{indent}{extra.text}')
            extra_content = '\n'.join(extra_parts)

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
        )

        is_tool = card.badge_category in (
            'tool',
            'shell',
            'terminal',
            'files',
            'browser',
            'mcp',
            'workers',
            'code',
        )
        is_active = is_tool and card.secondary_kind == 'neutral'
        if is_active:
            widget.set_processing(True)
            self._clear_last_active_card_processing()
            widget.set_processing(True)
            self._last_active_card = widget
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

    def _apply_card_final_state(
        self,
        widget: Any,
        *,
        status: str,
        outcome: str | None,
        extra_content: str | None,
        collapse: bool,
        syntax_language: str | None,
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
        if collapse:
            try:
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
        collapse: bool = True,
        operation_label: str | None = None,
        syntax_language: str | None = None,
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
            diff_encoded=True,
            syntax_language='diff',
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
