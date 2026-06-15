"""Action renderers — browser domain."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object

from rich.text import Text

from backend.cli._typing import ActionRenderersHost
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli.layout_tokens import (
    ACTIVITY_CARD_TITLE_BROWSER,
)
from backend.cli.path_links import linkify_plain
from backend.ledger.action import (  # noqa: E402
    BrowseInteractiveAction,
    BrowserToolAction,
)


class _ActionBrowserMixin(_ActionRenderersBase):
    def _render_browser_tool_action(self, action: BrowserToolAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', '') or 'browser'
        params = getattr(action, 'params', None) or {}
        url = params.get('url') if isinstance(params, dict) else None
        if url:
            detail: str | Text = linkify_plain(
                str(url)[:500], link_files=True, link_urls=True
            )
            reasoning_detail = str(url)[:500]
        else:
            detail = str(cmd)
            reasoning_detail = detail
        self._print_activity(
            str(cmd),
            detail,
            None,
            title=ACTIVITY_CARD_TITLE_BROWSER,
            badge_label='browser',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, reasoning_detail, thought)
        self.refresh()

    def _render_browse_interactive_action(
        self, action: BrowseInteractiveAction
    ) -> None:
        self._flush_pending_tool_cards()
        browser_actions = getattr(action, 'browser_actions', '') or ''
        url_match = re.search(r'https?://[^\s\'")\]]+', browser_actions)
        if url_match:
            raw_url = url_match.group(0)[:500]
            detail: str | Text = linkify_plain(raw_url, link_files=True, link_urls=True)
            reasoning_detail = raw_url
        else:
            detail = 'interactive session'  # type: ignore[unreachable]
            reasoning_detail = detail
        self._print_activity(
            'Opened',
            detail,
            None,
            title=ACTIVITY_CARD_TITLE_BROWSER,
            badge_label='browser',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, reasoning_detail, thought)
        self.refresh()
