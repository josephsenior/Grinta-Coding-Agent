"""Native browser operations using browser-use (BrowserSession) — no nested Agent."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from urllib.parse import urlparse

from backend.core.constants import (
    BROWSER_CDP_NAVIGATE_TIMEOUT_SEC,
    BROWSER_EXTRACT_TIMEOUT_SEC,
    BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC,
    BROWSER_SCREENSHOT_MAX_INJECT_BYTES,
    BROWSER_SCREENSHOT_TIMEOUT_SEC,
    BROWSER_SESSION_START_TIMEOUT_SEC,
    BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC,
    BROWSER_SNAPSHOT_MAX_CHARS_FULL,
    BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE,
    BROWSER_WAIT_TIMEOUT_SEC,
)
from backend.core.logger import app_logger as logger
from backend.ledger.observation import (
    BrowserScreenshotObservation,
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)

_MAX_URL_LEN = 2048
_MAX_TYPE_LEN = 8000

_INDEX_LINE_RE = re.compile(r'^\s*\[\d+\]')


StructuredExtractFn = Callable[
    [str, dict[str, Any], str | None], Awaitable[str]
]


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


def _interactive_index_lines(full_text: str) -> list[str]:
    """Lines that look like browser-use index markers ``[n]``."""
    out: list[str] = []
    for line in full_text.splitlines():
        s = line.rstrip()
        if _INDEX_LINE_RE.match(s):
            out.append(s)
    return out


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

    def __init__(
        self,
        downloads_dir: Path | str,
        *,
        workspace_root: Path | str | None = None,
    ) -> None:
        self._downloads = Path(downloads_dir)
        self._downloads.mkdir(parents=True, exist_ok=True)
        self._session: Any = None
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else self._downloads.resolve().parent
        )
        self._last_diff_lines: set[str] | None = None
        self._structured_extract: StructuredExtractFn | None = None

    def set_structured_extract(self, fn: StructuredExtractFn | None) -> None:
        """LLM-based JSON extract for ``browser extract`` (set by runtime bootstrap)."""
        self._structured_extract = fn

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

    async def _snapshot_formatted(self, browser: Any, mode: str) -> str:
        """Return DOM text for ``full`` / ``interactive`` / ``diff`` modes."""
        try:
            raw_text = await asyncio.wait_for(
                _snapshot_text_chain(browser),
                timeout=BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC,
            )
        except TimeoutError:
            raise RuntimeError(
                f'Snapshot timed out after {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s.'
            ) from None

        if mode == 'full':
            cap = BROWSER_SNAPSHOT_MAX_CHARS_FULL
            text = raw_text
        elif mode == 'interactive':
            lines = _interactive_index_lines(raw_text)
            cap = BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE
            text = '\n'.join(lines) if lines else raw_text[:cap]
        elif mode == 'diff':
            lines = _interactive_index_lines(raw_text)
            cur_set = set(lines)
            cap = BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE
            if self._last_diff_lines is None:
                text = '\n'.join(lines) if lines else raw_text[:cap]
            else:
                prev_set = self._last_diff_lines
                added = sorted(cur_set - prev_set)
                removed = sorted(prev_set - cur_set)
                parts: list[str] = []
                if added:
                    parts.append('Added:\n' + '\n'.join(added))
                if removed:
                    parts.append('Removed:\n' + '\n'.join(removed))
                text = '\n\n'.join(parts) if parts else '(no indexed element changes)'
            self._last_diff_lines = cur_set
        else:
            cap = BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE
            text = raw_text[:cap]

        if len(text) > cap:
            text = text[:cap] + '\n… (truncated)'
        return text

    async def _maybe_append_page_state(
        self,
        browser: Any,
        *,
        params: dict[str, Any],
        prefix: str,
    ) -> str:
        if not bool(params.get('return_state', True)):
            return prefix
        try:
            snap = await self._snapshot_formatted(browser, 'interactive')
        except RuntimeError as exc:
            return f'{prefix}\n--- page state ---\nERROR: {exc}'
        return f'{prefix}\n--- page state ---\n{snap}'

    async def _execute_start(self, cmd: str, params: dict[str, Any]) -> Observation:
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

    async def _execute_close(self, cmd: str, params: dict[str, Any]) -> Observation:
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
            await asyncio.wait_for(
                _navigate_direct_cdp(browser, url), timeout=nav_budget
            )
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

    async def _execute_navigate(self, cmd: str, params: dict[str, Any]) -> Observation:
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
        base = f'Navigated to {url}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content,
                command='browser navigate',
                exit_code=0,
            ),
        )

    async def _execute_snapshot(self, cmd: str, params: dict[str, Any]) -> Observation:
        mode = str(params.get('mode') or 'interactive').strip().lower()
        if mode not in ('full', 'interactive', 'diff'):
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content='ERROR: snapshot mode must be full, interactive, or diff.'
                ),
            )
        browser = await self._ensure_session()
        t_snap = time.monotonic()
        _browser_trace(
            f'snapshot chain begin mode={mode} (budget {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s)'
        )
        try:
            text = await self._snapshot_formatted(browser, mode)
        except RuntimeError as e:
            _browser_trace(f'snapshot failed: {e}')
            return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {e}'))

        elapsed_ms = (time.monotonic() - t_snap) * 1000
        _browser_trace(f'snapshot done in {elapsed_ms:.0f}ms')
        logger.info('browser snapshot chain in %.0fms', elapsed_ms)
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
        inject_image = bool(params.get('inject_image', True))
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
        raw_len = len(raw or b'')
        body = f'Screenshot saved to: {path} ({raw_len} bytes)'
        b64_payload = base64.b64encode(raw or b'').decode('ascii')
        inject_skip: str | None = None
        if not inject_image:
            inject_skip = 'inject_image=false'
            b64_payload = ''
        elif raw_len > BROWSER_SCREENSHOT_MAX_INJECT_BYTES:
            inject_skip = (
                f'JPEG exceeds max inject size ({BROWSER_SCREENSHOT_MAX_INJECT_BYTES} bytes); '
                'path-only caption preserved.'
            )
            b64_payload = ''
        return _finalize_observation(
            cmd,
            BrowserScreenshotObservation(
                content=body,
                image_path=str(path),
                image_b64=b64_payload,
                image_mime='image/jpeg',
                inject_skipped_reason=inject_skip,
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
        node = await browser.get_element_by_index(index)
        if node is not None:
            return node, None
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

    async def _execute_click(self, cmd: str, params: dict[str, Any]) -> Observation:
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
        base = f'Clicked element index {index}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content,
                command='browser click',
                exit_code=0,
            ),
        )

    async def _execute_type(self, cmd: str, params: dict[str, Any]) -> Observation:
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

        evt = browser.event_bus.dispatch(
            TypeTextEvent(node=node, text=text, clear=clear)
        )
        await evt
        await evt.event_result(raise_if_any=True, raise_if_none=False)
        base = f'Typed into element index {index}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content,
                command='browser type',
                exit_code=0,
            ),
        )

    def _resolve_workspace_path(self, raw: str) -> tuple[Path | None, str | None]:
        p = Path(raw).expanduser()
        root = self._workspace_root.resolve()
        candidate = (root / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None, f'Path must be under workspace root {root}'
        if not candidate.is_file():
            return None, f'Not a file: {candidate}'
        return candidate, None

    @staticmethod
    def _page_targets_ordered(browser: Any) -> list[Any]:
        try:
            pages = browser.get_page_targets()
        except Exception:
            pages = []
        return list(pages or [])

    async def _dispatch_bus_event(self, browser: Any, event_obj: Any) -> None:
        evt = browser.event_bus.dispatch(event_obj)
        await evt
        await evt.event_result(raise_if_any=True, raise_if_none=False)

    async def _execute_scroll(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import ScrollEvent, ScrollToTextEvent

        direction = str(params.get('direction') or 'down').strip().lower()
        browser = await self._ensure_session()
        to_text = params.get('to_text')
        if to_text:
            text = str(to_text).strip()
            if not text:
                return _finalize_observation(
                    cmd, ErrorObservation(content='ERROR: to_text is empty.')
                )
            await self._dispatch_bus_event(
                browser, ScrollToTextEvent(text=text, direction='down')
            )
            base = 'Scrolled toward text match.'
        elif direction in ('top', 'bottom'):
            amt = 50_000
            dir1 = 'up' if direction == 'top' else 'down'
            await self._dispatch_bus_event(
                browser, ScrollEvent(direction=dir1, amount=amt, node=None)
            )
            base = f'Scrolled {direction}.'
        else:
            if direction not in ('up', 'down', 'left', 'right'):
                return _finalize_observation(
                    cmd,
                    ErrorObservation(content='ERROR: invalid direction for scroll.'),
                )
            px = params.get('pixels')
            amount = int(px) if px is not None else 500
            node = None
            if params.get('scroll_index') is not None:
                six, err = self._parse_browser_index(
                    cmd, params.get('scroll_index'), action_name='scroll'
                )
                if err is not None:
                    return err
                node, err2 = await self._get_browser_node(
                    browser, cmd=cmd, index=six or 0
                )
                if err2 is not None:
                    return err2
            await self._dispatch_bus_event(
                browser,
                ScrollEvent(direction=direction, amount=amount, node=node),
            )
            base = f'Scrolled {direction} by {amount}px.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser scroll', exit_code=0
            ),
        )

    async def _execute_send_keys(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import SendKeysEvent

        keys = str(params.get('keys') or '').strip()
        if not keys:
            return _finalize_observation(
                cmd, ErrorObservation(content='ERROR: keys required.')
            )
        browser = await self._ensure_session()
        await self._dispatch_bus_event(browser, SendKeysEvent(keys=keys))
        base = f'Sent keys: {keys!r}'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser send_keys', exit_code=0
            ),
        )

    async def _execute_wait(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import WaitEvent

        wait_kind = str(
            params.get('wait_kind') or params.get('wait_for') or 'timeout'
        ).strip().lower()
        timeout_sec = float(params.get('timeout_sec') or 10.0)
        timeout_sec = min(timeout_sec, BROWSER_WAIT_TIMEOUT_SEC)
        browser = await self._ensure_session()

        if wait_kind == 'timeout':
            sec = min(float(params.get('seconds') or timeout_sec), 10.0)
            await self._dispatch_bus_event(browser, WaitEvent(seconds=sec))
            base = f'Waited {sec}s.'
        elif wait_kind == 'text':
            needle = str(params.get('value') or '').strip()
            if not needle:
                return _finalize_observation(
                    cmd,
                    ErrorObservation(content='ERROR: value required for text wait.'),
                )
            deadline = time.monotonic() + timeout_sec
            found = False
            while time.monotonic() < deadline:
                txt = await _snapshot_text_chain(browser)
                if needle in txt:
                    found = True
                    break
                await asyncio.sleep(0.4)
            if not found:
                return _finalize_observation(
                    cmd,
                    ErrorObservation(
                        content=(
                            f'ERROR: Timeout waiting for text after {timeout_sec:.0f}s.'
                        )
                    ),
                )
            base = 'Text appeared.'
        elif wait_kind in ('selector', 'css'):
            needle = str(params.get('value') or '').strip()
            if not needle:
                return _finalize_observation(
                    cmd,
                    ErrorObservation(
                        content='ERROR: value required for selector wait.'
                    ),
                )
            deadline = time.monotonic() + timeout_sec
            found = False
            while time.monotonic() < deadline:
                txt = await _snapshot_text_chain(browser)
                if needle in txt:
                    found = True
                    break
                await asyncio.sleep(0.4)
            if not found:
                return _finalize_observation(
                    cmd,
                    ErrorObservation(
                        content=(
                            f'ERROR: Timeout waiting for selector substring after '
                            f'{timeout_sec:.0f}s.'
                        )
                    ),
                )
            base = 'Selector/text appeared in DOM dump.'
        elif wait_kind == 'network_idle':
            prev: str | None = None
            deadline = time.monotonic() + timeout_sec
            stable = False
            while time.monotonic() < deadline:
                cur = await _snapshot_text_chain(browser)
                if prev is not None and cur == prev:
                    stable = True
                    break
                prev = cur
                await asyncio.sleep(0.5)
            if not stable:
                return _finalize_observation(
                    cmd,
                    ErrorObservation(
                        content=(
                            f'ERROR: Timeout waiting for stable DOM after '
                            f'{timeout_sec:.0f}s.'
                        )
                    ),
                )
            base = 'DOM stable (network_idle heuristic).'
        else:
            return _finalize_observation(
                cmd,
                ErrorObservation(content=f'ERROR: unknown wait_kind {wait_kind!r}.'),
            )

        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(content=content, command='browser wait', exit_code=0),
        )

    async def _execute_switch_tab(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import SwitchTabEvent

        idx, err = self._parse_browser_index(
            cmd, params.get('index'), action_name='switch_tab'
        )
        if err is not None:
            return err
        browser = await self._ensure_session()
        pages = self._page_targets_ordered(browser)
        if idx is None or idx < 0 or idx >= len(pages):
            return _finalize_observation(
                cmd,
                ErrorObservation(content=f'ERROR: invalid tab index {idx}.'),
            )
        tid = pages[idx].target_id
        await self._dispatch_bus_event(browser, SwitchTabEvent(target_id=tid))
        base = f'Switched to tab index {idx}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser switch_tab', exit_code=0
            ),
        )

    async def _execute_close_tab(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import CloseTabEvent

        idx, err = self._parse_browser_index(
            cmd, params.get('index'), action_name='close_tab'
        )
        if err is not None:
            return err
        browser = await self._ensure_session()
        pages = self._page_targets_ordered(browser)
        if idx is None or idx < 0 or idx >= len(pages):
            return _finalize_observation(
                cmd,
                ErrorObservation(content=f'ERROR: invalid tab index {idx}.'),
            )
        tid = pages[idx].target_id
        await self._dispatch_bus_event(browser, CloseTabEvent(target_id=tid))
        base = f'Closed tab index {idx}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser close_tab', exit_code=0
            ),
        )

    async def _execute_list_tabs(self, cmd: str, params: dict[str, Any]) -> Observation:
        del params
        browser = await self._ensure_session()
        pages = self._page_targets_ordered(browser)
        rows: list[dict[str, Any]] = []
        for i, p in enumerate(pages):
            rows.append(
                {
                    'index': i,
                    'url': getattr(p, 'url', '') or '',
                    'title': getattr(p, 'title', '') or '',
                }
            )
        body = json.dumps(rows, ensure_ascii=False, indent=2)
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=body, command='browser list_tabs', exit_code=0
            ),
        )

    async def _execute_go_back(self, cmd: str, params: dict[str, Any]) -> Observation:
        from browser_use.browser.events import GoBackEvent

        del params
        browser = await self._ensure_session()
        await self._dispatch_bus_event(browser, GoBackEvent())
        base = 'Navigated back in history.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser go_back', exit_code=0
            ),
        )

    async def _execute_extract(self, cmd: str, params: dict[str, Any]) -> Observation:
        if self._structured_extract is None:
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=(
                        'ERROR: Structured extract is not configured on this runtime.'
                    )
                ),
            )
        schema = params.get('schema')
        if not isinstance(schema, dict):
            return _finalize_observation(
                cmd,
                ErrorObservation(content='ERROR: extract requires schema object.'),
            )
        instruction = params.get('instruction')
        inst_str = str(instruction).strip() if instruction else None
        browser = await self._ensure_session()
        page_text = await self._snapshot_formatted(browser, 'full')
        try:
            out = await asyncio.wait_for(
                self._structured_extract(page_text, schema, inst_str),
                timeout=BROWSER_EXTRACT_TIMEOUT_SEC,
            )
        except TimeoutError:
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=(
                        f'ERROR: extract timed out after {BROWSER_EXTRACT_TIMEOUT_SEC:.0f}s.'
                    )
                ),
            )
        except Exception as exc:
            return _finalize_observation(
                cmd, ErrorObservation(content=f'ERROR: extract failed: {exc}')
            )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=out, command='browser extract', exit_code=0
            ),
        )

    async def _execute_upload_file(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        from browser_use.browser.events import UploadFileEvent

        raw_path = str(params.get('path') or '').strip()
        resolved, perr = self._resolve_workspace_path(raw_path)
        if perr:
            return _finalize_observation(
                cmd, ErrorObservation(content=f'ERROR: {perr}')
            )
        if resolved is None:
            return _finalize_observation(
                cmd, ErrorObservation(content='ERROR: could not resolve upload path.')
            )
        idx, err = self._parse_browser_index(
            cmd, params.get('index'), action_name='upload_file'
        )
        if err is not None:
            return err
        browser = await self._ensure_session()
        node, err2 = await self._get_browser_node(browser, cmd=cmd, index=idx or 0)
        if err2 is not None:
            return err2
        await self._dispatch_bus_event(
            browser, UploadFileEvent(node=node, file_path=str(resolved))
        )
        base = f'Uploaded {resolved.name} to element index {idx}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content, command='browser upload_file', exit_code=0
            ),
        )

    async def _execute_select_dropdown(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        from browser_use.browser.events import SelectDropdownOptionEvent

        opt_text = params.get('option_text')
        opt_val = params.get('option_value')
        choice = (
            (str(opt_text).strip() if opt_text else '')
            or (str(opt_val).strip() if opt_val else '')
        )
        if not choice:
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content='ERROR: option_text or option_value required.'
                ),
            )
        idx, err = self._parse_browser_index(
            cmd, params.get('index'), action_name='select_dropdown_option'
        )
        if err is not None:
            return err
        browser = await self._ensure_session()
        node, err2 = await self._get_browser_node(browser, cmd=cmd, index=idx or 0)
        if err2 is not None:
            return err2
        await self._dispatch_bus_event(
            browser, SelectDropdownOptionEvent(node=node, text=choice)
        )
        base = f'Selected dropdown option {choice!r} at index {idx}.'
        content = await self._maybe_append_page_state(
            browser, params=params, prefix=base
        )
        return _finalize_observation(
            cmd,
            CmdOutputObservation(
                content=content,
                command='browser select_dropdown_option',
                exit_code=0,
            ),
        )

    @staticmethod
    def _unknown_browser_command(cmd: str) -> Observation:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=f'ERROR: Unknown browser command {cmd!r}. '
                'Use: start, close, navigate, snapshot, screenshot, click, type, '
                'scroll, send_keys, wait, switch_tab, close_tab, list_tabs, go_back, '
                'extract, upload_file, select_dropdown_option.'
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
                'scroll': self._execute_scroll,
                'send_keys': self._execute_send_keys,
                'wait': self._execute_wait,
                'switch_tab': self._execute_switch_tab,
                'close_tab': self._execute_close_tab,
                'list_tabs': self._execute_list_tabs,
                'go_back': self._execute_go_back,
                'extract': self._execute_extract,
                'upload_file': self._execute_upload_file,
                'select_dropdown_option': self._execute_select_dropdown,
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
