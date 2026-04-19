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
from backend.ledger.observation import CmdOutputObservation, ErrorObservation, Observation

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
        raise RuntimeError('Browser has no focused page; call start or navigate on a running session.')
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

    async def execute(self, command: str, params: dict[str, Any]) -> Observation:
        cmd = (command or '').strip().lower()
        try:
            if cmd == 'start':
                await self._ensure_session()
                return _finalize_observation(
                    cmd,
                    CmdOutputObservation(
                        content='Browser started.',
                        command='browser start',
                        exit_code=0,
                    ),
                )
            if cmd == 'close':
                await self.shutdown()
                return _finalize_observation(
                    cmd,
                    CmdOutputObservation(
                        content='Browser closed.',
                        command='browser close',
                        exit_code=0,
                    ),
                )
            if cmd == 'navigate':
                url = str(params.get('url') or '').strip()
                err = _validate_http_url(url)
                if err:
                    return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {err}'))
                t_nav = time.monotonic()
                b = await self._ensure_session()
                new_tab = bool(params.get('new_tab', False))
                _browser_trace(
                    f'navigate begin (new_tab={new_tab}) budget {BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC:.0f}s → {url[:120]}'
                )
                # Avoid NavigateToUrlEvent: it chains SwitchTabEvent, extension cleanup, etc., which
                # can block for minutes on Windows Chrome while the tab already shows the URL.
                # Direct CDP Page.navigate matches commit semantics; use snapshot for DOM text.
                nav_budget = float(BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC)
                try:
                    if not new_tab:
                        await asyncio.wait_for(
                            _navigate_direct_cdp(b, url),
                            timeout=nav_budget,
                        )
                    else:
                        from browser_use.browser.events import NavigateToUrlEvent

                        nav = b.event_bus.dispatch(
                            NavigateToUrlEvent(
                                url=url,
                                new_tab=True,
                                wait_until='commit',
                            )
                        )
                        await asyncio.wait_for(
                            _await_nav_event(nav),
                            timeout=nav_budget,
                        )
                except TimeoutError:
                    _browser_trace(
                        f'navigate timed out after {nav_budget:.0f}s (CDP session + Page.navigate)'
                    )
                    return _finalize_observation(
                        cmd,
                        ErrorObservation(
                            content=(
                                f'ERROR: Navigation to {url} timed out after {nav_budget:.0f}s '
                                '(CDP session + Page.navigate). Retry or restart the CLI; '
                                'close other Chrome instances if the profile is wedged.'
                            )
                        ),
                    )
                _browser_trace(
                    f'navigate done in {(time.monotonic() - t_nav) * 1000:.0f}ms'
                )
                logger.info(
                    'browser navigate done in %.0fms',
                    (time.monotonic() - t_nav) * 1000,
                )
                return _finalize_observation(
                    cmd,
                    CmdOutputObservation(
                        content=f'Navigated to {url}.',
                        command='browser navigate',
                        exit_code=0,
                    ),
                )
            if cmd == 'snapshot':
                b = await self._ensure_session()
                t_snap = time.monotonic()
                _browser_trace(
                    f'snapshot chain begin (budget {BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC:.0f}s)'
                )
                try:
                    text = await asyncio.wait_for(
                        _snapshot_text_chain(b),
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
                _browser_trace(
                    f'snapshot done in {(time.monotonic() - t_snap) * 1000:.0f}ms'
                )
                logger.info(
                    'browser snapshot chain in %.0fms',
                    (time.monotonic() - t_snap) * 1000,
                )
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
            if cmd == 'screenshot':
                b = await self._ensure_session()
                full_page = bool(params.get('full_page', False))
                try:
                    raw = await asyncio.wait_for(
                        b.take_screenshot(full_page=full_page, format='png'),
                        timeout=BROWSER_SCREENSHOT_TIMEOUT_SEC,
                    )
                except TimeoutError:
                    return _finalize_observation(
                        cmd,
                        ErrorObservation(
                            content=(
                                f'ERROR: Screenshot timed out after {BROWSER_SCREENSHOT_TIMEOUT_SEC:.0f}s.'
                            )
                        ),
                    )
                name = f'browser_{uuid.uuid4().hex[:12]}.png'
                path = self._downloads / name
                path.write_bytes(raw)
                body = f'Screenshot saved to: {path} ({len(raw)} bytes)'
                return _finalize_observation(
                    cmd,
                    CmdOutputObservation(
                        content=body,
                        command='browser screenshot',
                        exit_code=0,
                    ),
                )
            if cmd == 'click':
                index = params.get('index')
                if not isinstance(index, int):
                    try:
                        index = int(index)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        return _finalize_observation(
                            cmd,
                            ErrorObservation(
                                content='ERROR: click requires integer index (from snapshot).'
                            ),
                        )
                b = await self._ensure_session()
                await b.get_browser_state_summary(include_screenshot=False)
                node = await b.get_element_by_index(index)
                if node is None:
                    return _finalize_observation(
                        cmd,
                        ErrorObservation(
                            content=f'ERROR: No element at index {index}. Run snapshot first.'
                        ),
                    )
                from browser_use.browser.events import ClickElementEvent

                evt = b.event_bus.dispatch(ClickElementEvent(node=node))
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
            if cmd == 'type':
                index = params.get('index')
                text = str(params.get('text') or '')
                if len(text) > _MAX_TYPE_LEN:
                    return _finalize_observation(
                        cmd, ErrorObservation(content='ERROR: text too long.')
                    )
                if not isinstance(index, int):
                    try:
                        index = int(index)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        return _finalize_observation(
                            cmd,
                            ErrorObservation(
                                content='ERROR: type requires integer index (from snapshot).'
                            ),
                        )
                b = await self._ensure_session()
                await b.get_browser_state_summary(include_screenshot=False)
                node = await b.get_element_by_index(index)
                if node is None:
                    return _finalize_observation(
                        cmd,
                        ErrorObservation(
                            content=f'ERROR: No element at index {index}. Run snapshot first.'
                        ),
                    )
                clear = bool(params.get('clear', True))
                from browser_use.browser.events import TypeTextEvent

                evt = b.event_bus.dispatch(
                    TypeTextEvent(node=node, text=text, clear=clear)
                )
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
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: Unknown browser command {cmd!r}. '
                    f'Use: start, close, navigate, snapshot, screenshot, click, type.'
                ),
            )
        except RuntimeError as e:
            return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {e}'))
        except Exception as e:
            # WARNING is below the CLI's effective ERROR level and would be dropped.
            logger.error('browser tool failed: %s', e, exc_info=True)
            _browser_trace(f'exception: {type(e).__name__}: {e}')
            msg = str(e).strip() or type(e).__name__
            hint = ''
            if 'chromium' in msg.lower() or 'browser' in msg.lower() and 'executable' in msg.lower():
                hint = ' If the browser binary is missing, run: uvx browser-use install'
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: Browser operation failed: {msg}.{hint}'
                ),
            )
