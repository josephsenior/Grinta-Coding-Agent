"""CDP low-level helpers for the Grinta native browser module.

These functions operate directly on the underlying CDP (Chrome
DevTools Protocol) client — they don't go through the browser-use
event bus. Used by the direct-CDP navigate path
(``_navigate_direct_cdp``).

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public ``GrintaNativeBrowser`` class and
``execute`` dispatcher.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def _navigate_direct_cdp(
    browser: Any, url: str, *, timeout_sec: float | None = None
) -> None:
    """Navigate without browser-use's NavigateToUrlEvent (avoids SwitchTab/DOM watchdog hangs).

    Uses the same CDP call as BrowserSession._navigate_and_wait at wait_until=commit.
    """
    from backend.core.constants import BROWSER_CDP_NAVIGATE_TIMEOUT_SEC
    from backend.execution.browser._browser_shared import _browser_trace

    if timeout_sec is None:
        timeout_sec = BROWSER_CDP_NAVIGATE_TIMEOUT_SEC

    if not getattr(browser, 'agent_focus_target_id', None):
        raise RuntimeError(
            'Browser has no focused page; call start or navigate on a running session.'
        )
    _browser_trace('CDP get_or_create_cdp_session…')
    cdp_session = await browser.get_or_create_cdp_session(None, focus=True)
    _browser_trace(f'CDP Page.navigate (inner cap {timeout_sec:.0f}s)…')
    nav_result = await asyncio.wait_for(
        cdp_session.cdp_client.send.Page.navigate(
            params={'url': url, 'transitionType': 'address_bar'},
            session_id=cdp_session.session_id,
        ),
        timeout=timeout_sec,
    )
    if nav_result.get('errorText'):
        raise RuntimeError(f'Navigation failed: {nav_result["errorText"]}')
