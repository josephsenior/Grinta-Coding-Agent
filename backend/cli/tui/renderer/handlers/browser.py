"""Browser tool event handlers — now append BrowserCard (scan-line) per action."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tui.renderer.helpers.browser import (
    resolve_browser_action_url,
    should_update_browser_card,
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
    )
    orch._last_browser_action_card = None
    orch._last_browser_cmd = 'browse'


def _handle_browser_screenshot_observation(
    orch: 'RendererEventProcessorMixin', event: BrowserScreenshotObservation
) -> None:
    content = (event.content or '').strip()
    image_path = getattr(event, 'image_path', '') or ''
    url = image_path or ''
    domain = orch._extract_browser_domain(url)
    orch._create_browser_scan_card(
        action=content or 'screenshot captured',
        domain=domain,
        full_url=url,
    )
