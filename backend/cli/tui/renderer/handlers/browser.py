"""Browser tool event handlers — now append BrowserCard (scan-line) per action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.renderer.helpers.browser import (
    resolve_browser_action_url,
)
from backend.ledger.action import BrowseInteractiveAction, BrowserToolAction
from backend.ledger.observation import BrowserScreenshotObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_browser_tool_action(
    orch: 'RendererEventProcessorMixin', event: BrowserToolAction
) -> None:
    action_name = getattr(event, 'command', 'browser') or 'browser'
    url = resolve_browser_action_url(action_name, event) or ''
    domain = orch._extract_browser_domain(url)
    orch._create_browser_scan_card(
        action=action_name,
        domain=domain,
        full_url=url,
        action_id=getattr(event, 'id', None),
    )
    orch._last_browser_action_card = None
    orch._last_browser_cmd = action_name


def _handle_browse_interactive_action(
    orch: 'RendererEventProcessorMixin', event: BrowseInteractiveAction
) -> None:
    actions = getattr(event, 'browser_actions', '') or ''
    detail = actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
    url = getattr(event, 'url', '') or ''
    domain = orch._extract_browser_domain(url)
    orch._create_browser_scan_card(
        action=detail or 'browse',
        domain=domain,
        full_url=url,
        action_id=getattr(event, 'id', None),
    )
    orch._last_browser_action_card = None
    orch._last_browser_cmd = 'browse'


def _handle_browser_screenshot_observation(
    orch: 'RendererEventProcessorMixin', event: BrowserScreenshotObservation
) -> None:
    content = (event.content or '').strip()
    domain = orch._extract_browser_domain(content)
    card = orch._take_tool_card(getattr(event, 'cause', None), expected_kind='browser')
    if card is not None:
        card.extracted = content
        if domain:
            card.domain = domain
        card.set_state('done')
        card._refresh_line()
        return
    orch._create_browser_scan_card(
        action=content or 'screenshot captured',
        domain=domain,
        full_url='',
        extracted=content or 'screenshot captured',
    )
