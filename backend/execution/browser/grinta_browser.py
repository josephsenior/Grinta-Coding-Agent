"""Native browser operations using browser-use (BrowserSession) — no nested Agent."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.core.constants import (
    BROWSER_CDP_NAVIGATE_TIMEOUT_SEC,
    BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC,
    BROWSER_SCREENSHOT_TIMEOUT_SEC,
    BROWSER_SESSION_START_TIMEOUT_SEC,
    BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC,
)
from backend.core.logger import app_logger as logger
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)

_MAX_SNAPSHOT_CHARS = 120_000
_MAX_URL_LEN = 2048
_MAX_TYPE_LEN = 8000


def _browser_trace(msg: str) -> None:
    """Print to stderr when GRINTA_BROWSER_TRACE is set.

    The interactive CLI forces ``app`` logging to ERROR and uses NullHandlers so Rich
    can own the terminal; INFO/WARNING from this module are otherwise invisible.
    """
    raw = os.environ.get('GRINTA_BROWSER_TRACE', '').strip().lower()
    if raw not in ('1', 'true', 'yes', 'on'):
        return
    print(f'[grinta-browser] {msg}', file=sys.stderr, flush=True)


def _validate_http_url(url: str) -> str | None:
    if not url or len(url) > _MAX_URL_LEN:
        return 'Invalid or overly long url.'
    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https'):
        return 'Only http and https URLs are allowed.'
    if not parsed.netloc:
        return 'URL must include a host.'
    return None


async def _navigate_direct_cdp(
    browser: Any, url: str, *, timeout_sec: float = BROWSER_CDP_NAVIGATE_TIMEOUT_SEC
) -> None:
    """Navigate without browser-use's NavigateToUrlEvent (avoids SwitchTab/DOM watchdog hangs).

    Uses the same CDP call as BrowserSession._navigate_and_wait at wait_until=commit.
    """
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


async def _await_nav_event(nav: Any) -> None:
    await nav
    await nav.event_result(raise_if_any=True, raise_if_none=False)


async def _snapshot_text_chain(browser: Any) -> str:
    await browser.get_browser_state_summary(include_screenshot=False)
    return await browser.get_state_as_text()


def _finalize_observation(cmd: str, obs: Observation) -> Observation:
    """Trace right before leaving ``execute`` (stderr when GRINTA_BROWSER_TRACE=1)."""
    _browser_trace(f'execute return command={cmd!r} → {type(obs).__name__}')
    return obs


def _resolve_page_target_id(browser: Any) -> str | None:
    """Return a target_id guaranteed to be a top-level page/tab.

    ``BrowserSession.take_screenshot`` uses the current ``agent_focus_target_id``
    with no type check. If focus ever lands on an iframe/worker (can happen
    after a redirect inside an embedded frame), ``Page.captureScreenshot``
    silently hangs on Windows instead of erroring. So we mirror the logic in
    ``ScreenshotWatchdog``: prefer focus when it *is* a page, otherwise fall
    back to the last known page target.
    """
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
    import base64

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


class GrintaNativeBrowser:
    """Thin async wrapper around browser_use.Browser (BrowserSession)."""

    def __init__(self, downloads_dir: Path | str) -> None:
        self._downloads = Path(downloads_dir)
        self._downloads.mkdir(parents=True, exist_ok=True)
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            from browser_use import Browser as BrowserCls
        except ImportError as e:
            raise RuntimeError(
                'browser-use is not installed. Install the optional dependency group '
                '(`uv sync --group browser`) and run `uvx browser-use install` to '
                'download Chromium.'
            ) from e
        browser = BrowserCls()
        t0 = time.monotonic()
        _browser_trace(
            f'starting Chromium (budget {BROWSER_SESSION_START_TIMEOUT_SEC:.0f}s; '
            'pre-run: uvx browser-use install)'
        )
        logger.info(
            'browser-use: starting Chromium (timeout %.0fs; pre-run: uvx browser-use install).',
            BROWSER_SESSION_START_TIMEOUT_SEC,
        )
        try:
            await asyncio.wait_for(
                browser.start(),
                timeout=BROWSER_SESSION_START_TIMEOUT_SEC,
            )
        except TimeoutError as e:
            _browser_trace('Chromium start timed out (asyncio.wait_for)')
            raise RuntimeError(
                f'Browser failed to start within {BROWSER_SESSION_START_TIMEOUT_SEC:.0f}s. '
                'Pre-install Chromium when possible: uvx browser-use install. '
                'Then retry; check disk space, VPN, and antivirus blocking the browser binary.'
            ) from e
        elapsed_ms = (time.monotonic() - t0) * 1000
        _browser_trace(f'Chromium session ready in {elapsed_ms:.0f}ms')
        logger.info('browser-use: Chromium session ready in %.0fms', elapsed_ms)
        self._session = browser
        return browser

    async def shutdown(self) -> None:
        if self._session is None:
            return
        try:
            await self._session.stop()
        except Exception as exc:
            logger.debug('browser stop: %s', exc)
        try:
            await self._session.close()
        except Exception as exc:
            logger.debug('browser close: %s', exc)
        self._session = None

    async def _execute_start(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        del params
        await self._ensure_session()
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content='Browser started.',
                command='browser start',
                exit_code=0,
            ),
        )

    async def _execute_close(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        del params
        await self.shutdown()
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content='Browser closed.',
                command='browser close',
                exit_code=0,
            ),
        )

    async def _run_navigation(
        self,
        browser: Any,
        *,
        url: str,
        new_tab: bool,
        nav_budget: float,
    ) -> None:
        if not new_tab:
            await asyncio.wait_for(_navigate_direct_cdp(browser, url), timeout=nav_budget)
            return

        from browser_use.browser.events import NavigateToUrlEvent

        nav = browser.event_bus.dispatch(
            NavigateToUrlEvent(
                url=url,
                new_tab=True,
                wait_until='commit',
            )
        )
        await asyncio.wait_for(_await_nav_event(nav), timeout=nav_budget)

    async def _execute_navigate(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        url = str(params.get('url') or '').strip()
        err = _validate_http_url(url)
        if err:
            return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {err}'))

        t_nav = time.monotonic()
        browser = await self._ensure_session()
        new_tab = bool(params.get('new_tab', False))
        _browser_trace(
            f'navigate begin (new_tab={new_tab}) budget {BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC:.0f}s → {url[:120]}'
        )
        try:
            await self._run_navigation(
                browser,
                url=url,
                new_tab=new_tab,
                nav_budget=float(BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC),
            )
        except TimeoutError:
            _browser_trace(
                f'navigate timed out after {BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC:.0f}s (CDP session + Page.navigate)'
            )
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=(
                        f'ERROR: Navigation to {url} timed out after {BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC:.0f}s '
                        '(CDP session + Page.navigate). Retry or restart the CLI; '
                        'close other Chrome instances if the profile is wedged.'
                    )
                ),
            )

        elapsed_ms = (time.monotonic() - t_nav) * 1000
        _browser_trace(f'navigate done in {elapsed_ms:.0f}ms')
        logger.info('browser navigate done in %.0fms', elapsed_ms)
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=f'Navigated to {url}.',
                command='browser navigate',
                exit_code=0,
            ),
        )

    async def _execute_snapshot(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        del params
        browser = await self._ensure_session()
        t_snap = time.monotonic()
        _browser_trace(
            f'snapshot chain begin (budget {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s)'
        )
        try:
            text = await asyncio.wait_for(
                _snapshot_text_chain(browser),
                timeout=BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC,
            )
        except TimeoutError:
            _browser_trace(
                f'snapshot timed out after {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s'
            )
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=(
                        f'ERROR: Snapshot timed out after {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s. '
                        'The page may be hung; try navigate again or restart the browser session.'
                    )
                ),
            )

        elapsed_ms = (time.monotonic() - t_snap) * 1000
        _browser_trace(f'snapshot done in {elapsed_ms:.0f}ms')
        logger.info('browser snapshot chain in %.0fms', elapsed_ms)
        if len(text) > _MAX_SNAPSHOT_CHARS:
            text = text[:_MAX_SNAPSHOT_CHARS] + '\n… (truncated)'
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=text,
                command='browser snapshot',
                exit_code=0,
            ),
        )

    @staticmethod
    def _screenshot_attach_error(cmd: str) -> Observation:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    'ERROR: Browser screenshot could not attach a CDP '
                    'session to a page target. Run ``browser navigate`` '
                    'to open/refresh a tab, then retry.'
                )
            ),
        )

    @staticmethod
    def _screenshot_failure_error(
        cmd: str,
        *,
        started_at: float,
        first_error: Exception | None,
        retry_error: Exception,
    ) -> Observation:
        total = time.monotonic() - started_at
        first = type(first_error).__name__ if first_error else 'TimeoutError'
        reason = (
            'The browser stayed busy or blocked on the page. '
            'Most common causes: a JavaScript alert/confirm/prompt '
            'dialog is still open (we tried to auto-dismiss it), '
            'a long CSS animation, or the tab lost rendering focus. '
            'Try ``browser snapshot`` to probe the DOM, or '
            '``browser navigate`` to the same URL to reset.'
        )
        _browser_trace(
            f'screenshot: both paths failed after {total:.1f}s '
            f'(primary={first}, retry={type(retry_error).__name__})'
        )
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    f'ERROR: Browser screenshot failed after {total:.0f}s '
                    '(tried compositor and window capture). '
                    f'First error: {first}. Retry error: '
                    f'{type(retry_error).__name__}. {reason}'
                )
            ),
        )

    async def _capture_screenshot_with_retry(
        self,
        browser: Any,
        *,
        cmd: str,
        target_id: Any,
        cdp: Any,
        full_page: bool,
        jpeg_quality: int,
        primary_budget: float,
        retry_budget: float,
        started_at: float,
    ) -> tuple[bytes | None, Observation | None]:
        try:
            raw = await _capture_via_cdp(
                cdp,
                full_page=full_page,
                jpeg_quality=jpeg_quality,
                from_surface=True,
                timeout_sec=primary_budget,
            )
            _browser_trace(
                f'screenshot done via compositor in {(time.monotonic() - started_at) * 1000:.0f}ms'
            )
            return raw, None
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            first_error = exc
            _browser_trace(
                f'screenshot: compositor path failed ({type(exc).__name__}); retrying with fromSurface=False'
            )

        try:
            retry_cdp = await _prepare_target_for_screenshot(browser, target_id) or cdp
            raw = await _capture_via_cdp(
                retry_cdp,
                full_page=full_page,
                jpeg_quality=jpeg_quality,
                from_surface=False,
                timeout_sec=retry_budget,
            )
            _browser_trace(
                f'screenshot done via fromSurface=False in {(time.monotonic() - started_at) * 1000:.0f}ms'
            )
            return raw, None
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            return None, self._screenshot_failure_error(
                cmd,
                started_at=started_at,
                first_error=first_error,
                retry_error=exc,
            )

    async def _execute_screenshot(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        browser = await self._ensure_session()
        full_page = bool(params.get('full_page', False))
        jpeg_quality = 80
        primary_budget = max(8.0, BROWSER_SCREENSHOT_TIMEOUT_SEC * 0.55)
        retry_budget = max(8.0, BROWSER_SCREENSHOT_TIMEOUT_SEC * 0.45)

        started_at = time.monotonic()
        target_id = _resolve_page_target_id(browser)
        _browser_trace(
            f'screenshot begin target={str(target_id)[:8]} full_page={full_page} budget={primary_budget:.0f}+{retry_budget:.0f}s'
        )
        cdp = await _prepare_target_for_screenshot(browser, target_id)
        if cdp is None:
            return self._screenshot_attach_error(cmd)

        raw, error_observation = await self._capture_screenshot_with_retry(
            browser,
            cmd=cmd,
            target_id=target_id,
            cdp=cdp,
            full_page=full_page,
            jpeg_quality=jpeg_quality,
            primary_budget=primary_budget,
            retry_budget=retry_budget,
            started_at=started_at,
        )
        if error_observation is not None:
            return error_observation

        name = f'browser_{uuid.uuid4().hex[:12]}.jpg'
        path = self._downloads / name
        path.write_bytes(raw or b'')
        body = f'Screenshot saved to: {path} ({len(raw or b"")} bytes)'
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=body,
                command='browser screenshot',
                exit_code=0,
            ),
        )

    @staticmethod
    def _parse_browser_index(
        cmd: str, value: Any, *, action_name: str
    ) -> tuple[int | None, Observation | None]:
        if isinstance(value, int):
            return value, None
        try:
            return int(value), None
        except (TypeError, ValueError):
            return None, _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: {action_name} requires integer index (from snapshot).'
                ),
            )

    async def _get_browser_node(
        self, browser: Any, *, cmd: str, index: int
    ) -> tuple[Any | None, Observation | None]:
        await browser.get_browser_state_summary(include_screenshot=False)
        node = await browser.get_element_by_index(index)
        if node is None:
            return None, _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: No element at index {index}. Run snapshot first.'
                ),
            )
        return node, None

    async def _execute_click(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        index, error_observation = self._parse_browser_index(
            cmd,
            params.get('index'),
            action_name='click',
        )
        if error_observation is not None:
            return error_observation

        browser = await self._ensure_session()
        node, error_observation = await self._get_browser_node(
            browser,
            cmd=cmd,
            index=index or 0,
        )
        if error_observation is not None:
            return error_observation

        from browser_use.browser.events import ClickElementEvent

        evt = browser.event_bus.dispatch(ClickElementEvent(node=node))
        await evt
        await evt.event_result(raise_if_any=True, raise_if_none=False)
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=f'Clicked element index {index}.',
                command='browser click',
                exit_code=0,
            ),
        )

    async def _execute_type(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        text = str(params.get('text') or '')
        if len(text) > _MAX_TYPE_LEN:
            return _finalize_observation(
                cmd,
                ErrorObservation(content='ERROR: text too long.'),
            )

        index, error_observation = self._parse_browser_index(
            cmd,
            params.get('index'),
            action_name='type',
        )
        if error_observation is not None:
            return error_observation

        browser = await self._ensure_session()
        node, error_observation = await self._get_browser_node(
            browser,
            cmd=cmd,
            index=index or 0,
        )
        if error_observation is not None:
            return error_observation

        clear = bool(params.get('clear', True))
        from browser_use.browser.events import TypeTextEvent

        evt = browser.event_bus.dispatch(TypeTextEvent(node=node, text=text, clear=clear))
        await evt
        await evt.event_result(raise_if_any=True, raise_if_none=False)
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=f'Typed into element index {index}.',
                command='browser type',
                exit_code=0,
            ),
        )

    @staticmethod
    def _unknown_browser_command(cmd: str) -> Observation:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=f'ERROR: Unknown browser command {cmd!r}. '
                'Use: start, close, navigate, snapshot, screenshot, click, type.'
            ),
        )

    async def execute(self, command: str, params: dict[str, Any]) -> Observation:
        cmd = (command or '').strip().lower()
        try:
            handlers = {
                'start': self._execute_start,
                'close': self._execute_close,
                'navigate': self._execute_navigate,
                'snapshot': self._execute_snapshot,
                'screenshot': self._execute_screenshot,
                'click': self._execute_click,
                'type': self._execute_type,
            }
            handler = handlers.get(cmd)
            if handler is None:
                return self._unknown_browser_command(cmd)
            return await handler(cmd, params)
        except RuntimeError as e:
            return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {e}'))
        except Exception as e:
            # WARNING is below the CLI's effective ERROR level and would be dropped.
            logger.error('browser tool failed: %s', e, exc_info=True)
            _browser_trace(f'exception: {type(e).__name__}: {e}')
            msg = str(e).strip() or type(e).__name__
            hint = ''
            if (
                'chromium' in msg.lower()
                or 'browser' in msg.lower()
                and 'executable' in msg.lower()
            ):
                hint = ' If the browser binary is missing, run: uvx browser-use install'
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: Browser operation failed: {msg}.{hint}'
                ),
            )
