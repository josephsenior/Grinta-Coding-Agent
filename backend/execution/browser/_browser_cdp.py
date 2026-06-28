"""CDP low-level helpers for the Grinta native browser module.

These functions operate directly on the underlying CDP (Chrome
DevTools Protocol) client — they don't go through the browser-use
event bus. Used by the screenshot path (``_resolve_page_target_id``,
``_prepare_target_for_screenshot``, ``_capture_via_cdp``) and the
direct-CDP navigate path (``_navigate_direct_cdp``).

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public ``GrintaNativeBrowser`` class and
``execute`` dispatcher.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any


def _resolve_page_target_id(browser: Any) -> str | None:
    """Return a target_id guaranteed to be a top-level page/tab.

    ``BrowserSession.take_screenshot`` uses the current ``agent_focus_target_id``
    with no type check. If focus ever lands on an iframe/worker (can happen
    after a redirect inside an embedded frame), ``Page.captureScreenshot``
    silently hangs on Windows instead of erroring. So we mirror the logic in
    ``ScreenshotWatchdog``: prefer focus when it *is* a page, otherwise fall
    back to the last known page target.
    """
    from backend.execution.browser._browser_shared import _browser_trace

    try:
        focused = browser.get_focused_target()
    except Exception as exc:  # noqa: BLE001
        _browser_trace(f'resolve_page_target: get_focused_target failed ({exc})')
        focused = None
    if focused is not None and getattr(focused, 'target_type', None) in ('page', 'tab'):
        return focused.target_id
    try:
        pages = browser.get_page_targets()
    except Exception as exc:  # noqa: BLE001
        _browser_trace(f'resolve_page_target: get_page_targets failed ({exc})')
        pages = []
    if pages:
        return pages[-1].target_id
    return getattr(browser, 'agent_focus_target_id', None)


async def _prepare_target_for_screenshot(browser: Any, target_id: str | None) -> Any:
    """Best-effort fixes applied right before CDP ``Page.captureScreenshot``.

    Two failure modes have been observed in the wild:

    1. A ``window.alert()`` / ``confirm()`` dialog is open on the page.
       Chrome blocks screenshot capture until the dialog is dismissed.
       The stock ``PopupsWatchdog`` only attaches on ``TabCreatedEvent``,
       which our direct-CDP navigate path bypasses — so we dismiss any
       live dialog here defensively.
    2. The tab lost foreground (another tool focused a different target).
       ``Page.bringToFront`` is cheap and restores rendering.

    Returns the CDP session used for the preflight so the caller can reuse
    it for the actual capture (saves another ``get_or_create_cdp_session``
    round-trip which itself waits up to 5s on focus validation).

    All errors are swallowed; a missing-dialog response is the normal case
    and must not make the caller give up on the screenshot.
    """
    from backend.execution.browser._browser_shared import _browser_trace

    try:
        cdp = await asyncio.wait_for(
            browser.get_or_create_cdp_session(target_id, focus=True),
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort preflight
        _browser_trace(f'screenshot preflight: no cdp session ({exc})')
        return None

    async def _safe(coro: Any, label: str, *, wait_s: float = 1.0) -> None:
        try:
            await asyncio.wait_for(coro, timeout=wait_s)
        except Exception as exc:  # noqa: BLE001
            _browser_trace(f'screenshot preflight {label}: {type(exc).__name__}')

    await _safe(
        cdp.cdp_client.send.Page.enable(session_id=cdp.session_id),
        'Page.enable',
    )
    await _safe(
        cdp.cdp_client.send.Page.bringToFront(session_id=cdp.session_id),
        'bringToFront',
    )
    await _safe(
        cdp.cdp_client.send.Page.handleJavaScriptDialog(
            params={'accept': True},
            session_id=cdp.session_id,
        ),
        'handleJavaScriptDialog',
    )
    return cdp


async def _focus_page_target(browser: Any, target_id: str | None) -> None:
    """Best-effort: point browser-use focus at a top-level page before capture."""
    from backend.execution.browser._browser_shared import _browser_trace

    if not target_id:
        return
    try:
        current = getattr(browser, 'agent_focus_target_id', None)
        if current == target_id:
            return
        setattr(browser, 'agent_focus_target_id', target_id)
        _browser_trace(f'screenshot focus: agent_focus_target_id={str(target_id)[:8]}')
    except Exception as exc:  # noqa: BLE001
        _browser_trace(f'screenshot focus skipped ({type(exc).__name__})')


async def _capture_via_browser_session(
    browser: Any,
    *,
    full_page: bool,
    jpeg_quality: int,
    timeout_sec: float,
) -> bytes | None:
    """Fallback capture via browser-use ``take_screenshot`` when CDP paths fail."""
    from backend.execution.browser._browser_shared import _browser_trace

    take_screenshot = getattr(browser, 'take_screenshot', None)
    if not callable(take_screenshot):
        return None
    try:
        raw = await asyncio.wait_for(
            take_screenshot(
                path=None,
                full_page=full_page,
                format='jpeg',
                quality=jpeg_quality,
            ),
            timeout=timeout_sec,
        )
    except Exception as exc:  # noqa: BLE001
        _browser_trace(
            f'screenshot: browser.take_screenshot fallback failed ({type(exc).__name__})'
        )
        return None
    if not raw:
        return None
    return bytes(raw)


async def _capture_via_cdp(
    cdp: Any,
    *,
    full_page: bool,
    jpeg_quality: int,
    from_surface: bool,
    timeout_sec: float,
) -> bytes:
    """Call ``Page.captureScreenshot`` directly and return PNG/JPEG bytes.

    - ``format='jpeg'`` + ``optimizeForSpeed=True`` is ~3-5x faster than PNG
      for typical pages and avoids the slow PNG encoder stalls observed on
      Windows headful Chromium.
    - ``fromSurface=False`` falls back to window capture instead of the GPU
      compositor surface. On Windows the compositor path frequently hangs
      when the tab isn't foregrounded or GPU is under pressure; window
      capture is simpler and much more reliable.
    """
    params: dict[str, Any] = {
        'format': 'jpeg',
        'quality': jpeg_quality,
        'captureBeyondViewport': full_page,
        'optimizeForSpeed': True,
        'fromSurface': from_surface,
    }
    result = await asyncio.wait_for(
        cdp.cdp_client.send.Page.captureScreenshot(
            params=params,
            session_id=cdp.session_id,
        ),
        timeout=timeout_sec,
    )
    if not result or 'data' not in result:
        raise RuntimeError('Page.captureScreenshot returned no data.')
    return base64.b64decode(result['data'])


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
