"""Pure browser event helpers (no orchestrator dependency)."""

from __future__ import annotations

from typing import Any

from backend.ledger.action import BrowserToolAction


def browser_navigate_url(event: BrowserToolAction) -> str:
    return (getattr(event, 'params', {}) or {}).get('url', '')


def browser_click_url(event: BrowserToolAction) -> str:
    selector = (getattr(event, 'params', {}) or {}).get('selector', '')
    return selector[:80] if selector else ''


def resolve_browser_action_url(action_name: str, event: BrowserToolAction) -> str:
    if action_name == 'navigate':
        return browser_navigate_url(event)
    if action_name == 'click':
        return browser_click_url(event)
    return ''


def build_screenshot_preview(url: str, content: str) -> str | None:
    extra_parts = []
    if url:
        extra_parts.append(f'URL: {url}')
    if content:
        extra_parts.append(content[:200])
    return '\n'.join(extra_parts) if extra_parts else None


def should_update_browser_card(prev: Any, last_cmd: str) -> bool:
    if prev is None:
        return False
    return last_cmd not in ('', 'screenshot')
