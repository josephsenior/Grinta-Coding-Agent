"""Browser tool event handlers (navigate, browse, screenshot)."""

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


def _update_browser_screenshot_card(
    orch: 'RendererEventProcessorMixin',
    prev: Any,
    last_cmd: str,
    url: str,
    content: str,
    *,
    image_path: str = '',
) -> None:
    card = ActivityRenderer.browser_action(
        last_cmd or 'screenshot',
        url,
        result=content or 'captured',
        image_path=image_path,
    )
    extra_content = ActivityRenderer.format_extra_lines(card.extra_lines)
    orch._update_record_panel_outcome(
        prev,
        status='ok',
        outcome=card.secondary or 'captured',
        extra_content=extra_content,
        meta_lines=card.meta_lines or None,
    )
    orch._last_browser_action_card = None


def _extract_screenshot_details(
    orch: 'RendererEventProcessorMixin',
    event: BrowserScreenshotObservation,
) -> tuple[str, str, Any, str]:
    url = getattr(event, 'image_path', '') or ''
    content = (event.content or '').strip()
    prev = getattr(orch, '_last_browser_action_card', None)
    last_cmd = getattr(orch, '_last_browser_cmd', '') or ''
    return url, content, prev, last_cmd


def _handle_browser_tool_action(
    orch: 'RendererEventProcessorMixin', event: BrowserToolAction
) -> None:
    action_name = getattr(event, 'command', 'browser') or 'browser'
    url = resolve_browser_action_url(action_name, event)
    card = ActivityRenderer.browser_action(action_name, url)
    widget = orch._write_record_card(card, processing=True)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = action_name


def _handle_browse_interactive_action(
    orch: 'RendererEventProcessorMixin', event: BrowseInteractiveAction
) -> None:
    actions = getattr(event, 'browser_actions', '') or ''
    detail = actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
    card = ActivityRenderer.browser_action('browse', detail)
    widget = orch._write_record_card(card, processing=True)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = 'browse'


def _handle_browser_screenshot_observation(
    orch: 'RendererEventProcessorMixin', event: BrowserScreenshotObservation
) -> None:
    url, content, prev, last_cmd = _extract_screenshot_details(orch, event)
    image_path = getattr(event, 'image_path', '') or ''
    screenshot_cmd = 'screenshot'
    card = ActivityRenderer.browser_action(
        screenshot_cmd,
        url,
        result=content or 'captured',
        image_path=image_path,
    )
    if should_update_browser_card(prev, last_cmd):
        _update_browser_screenshot_card(
            orch,
            prev,
            screenshot_cmd,
            url,
            content,
            image_path=image_path,
        )
    else:
        orch._write_record_card(card)
