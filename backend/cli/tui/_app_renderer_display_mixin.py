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

    def clear_history(self) -> None:
        self._live_thinking_widget = None
        self._live_response_widget = None
        self._terminal_cards_by_session = {}
        self._terminal_commands_by_session = {}
        self._pending_terminal_command = None
        self._pending_terminal_card = None
        self._pending_shell_cards_by_command = defaultdict(deque)
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
        try:
            self._tui._get_display().clear()
        except (AttributeError, NoMatches):
            pass
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh derived sidebar state; transcript writes are incremental."""
        from backend.cli._event_renderer.sidebar import _load_playbook_skills
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        _TASK_TO_SIDEBAR_STATUS = {
            'done': 'ok',
            'doing': 'running',
            'blocked': 'err',
            'todo': 'neutral',
            'skipped': 'warn',
        }

        mcp_count = self._hud.state.mcp_servers
        skill_count = self._hud.bundled_skill_count

        # Build actual MCP server list from config
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

        task_signature = task_panel_signature(self._task_list)
        current_state = (task_signature, mcp_servers, skill_count)
        if current_state != self._last_sidebar_state:
            # 1. Update Tasks Section
            try:
                tasks_widget = self._tui.query_one('#sidebar-tasks', CollapsibleSection)
                task_items = []
                for task_id, status, desc in task_signature:
                    item_status = _TASK_TO_SIDEBAR_STATUS.get(status, 'neutral')
                    meta = task_id if task_id and task_id != '?' else None
                    task_items.append(
                        (desc, f'task:{task_id}', False, item_status, meta)
                    )

                tasks_widget.set_title(f'Tasks ({len(task_signature)})')
                tasks_widget.set_items(task_items)
            except Exception:
                pass

            # 2. Update MCP Servers Section
            try:
                mcp_widget = self._tui.query_one('#sidebar-mcp', CollapsibleSection)
                mcp_items = []
                if mcp_servers:
                    for server in mcp_servers:
                        name = server.get('name', 'unknown')
                        server_type = server.get('type', 'stdio')
                        mcp_items.append(
                            (name, f'mcp:{name}', True, 'info', server_type)
                        )

                mcp_widget.set_title(
                    f'MCP Servers ({len(mcp_servers) if mcp_servers else 0})'
                )
                mcp_widget.set_items(mcp_items)
            except Exception:
                pass

            # 3. Update Skills Section
            try:
                skills_widget = self._tui.query_one(
                    '#sidebar-skills', CollapsibleSection
                )
                skills_list = _load_playbook_skills()
                skill_items = []
                if skills_list:
                    for skill in sorted(skills_list):
                        skill_items.append(
                            (skill, f'skill:{skill}', True, 'neutral', None)
                        )

                skills_widget.set_title(f'Skills ({len(skills_list)})')
                skills_widget.set_items(skill_items)
            except Exception:
                pass

            self._last_sidebar_state = current_state

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
        collapsed: bool = True,
    ) -> Any:
        """Write an activity card to the transcript using native ActivityCard widget."""
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
        is_active = is_tool and (not card.secondary or card.secondary_kind == 'neutral')
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
        display.append_widget(widget)
        return widget

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
        )
        self._tui.set_current_operation(
            f'{verb} {detail}'.strip(),
            meta=secondary or 'Completed',
            active=False,
        )
        display = self._tui._get_display()
        display.append_widget(widget)
