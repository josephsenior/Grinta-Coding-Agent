"""Snapshot and screenshot method bodies for GrintaNativeBrowser.

Module functions are extracted method bodies for the snapshot and
screenshot commands on ``GrintaNativeBrowser``. They are called as
one-line forwarders from the class. Module functions invoke other
methods via ``self._method(...)`` so monkey-patching of the class
methods in tests still works.

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public class and ``execute`` dispatcher.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Any

from backend.core.constants import (
    BROWSER_SCREENSHOT_MAX_INJECT_BYTES,
    BROWSER_SCREENSHOT_TIMEOUT_SEC,
    BROWSER_SNAPSHOT_CHAIN_TIMEOUT_SEC,
    BROWSER_SNAPSHOT_MAX_CHARS_FULL,
    BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE,
)
from backend.core.os_capabilities import OS_CAPS
from backend.execution.browser._browser_cdp import (
    _capture_via_browser_session,
    _capture_via_cdp,
    _focus_page_target,
    _prepare_target_for_screenshot,
    _resolve_page_target_id,
)
from backend.execution.browser._browser_shared import (
    _browser_trace,
    _finalize_observation,
    _interactive_index_lines,
    _snapshot_text_chain,
)
from backend.ledger.observation import (
    BrowserScreenshotObservation,
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)


async def snapshot_formatted_impl(self, browser: Any, mode: str) -> str:
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
        cap = BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE
        text = self._snapshot_diff(raw_text, cap)
    else:
        cap = BROWSER_SNAPSHOT_MAX_CHARS_INTERACTIVE
        text = raw_text[:cap]

    if len(text) > cap:
        text = text[:cap] + '\n… (truncated)'
    return text


def _snapshot_diff(self, raw_text: str, cap: int) -> str:
    lines = _interactive_index_lines(raw_text)
    cur_set = set(lines)
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
    return text


async def maybe_append_page_state_impl(
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


async def execute_snapshot_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
    from backend.core.logging.logger import app_logger as logger

    logger.info('browser snapshot chain in %.0fms', elapsed_ms)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=text,
            command='browser snapshot',
            exit_code=0,
        ),
    )


def screenshot_attach_error_impl(cmd: str) -> Observation:
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


def screenshot_failure_error_impl(
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
                '(tried window/compositor capture and browser.take_screenshot). '
                f'First error: {first}. Retry error: '
                f'{type(retry_error).__name__}. {reason}'
            )
        ),
    )


async def capture_screenshot_with_retry_impl(
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
    fallback_budget: float,
    started_at: float,
) -> tuple[bytes | None, Observation | None]:
    capture_order = (False, True) if OS_CAPS.is_windows else (True, False)
    first_error: Exception | None = None

    for idx, from_surface in enumerate(capture_order):
        budget = primary_budget if idx == 0 else retry_budget
        try:
            session_cdp = cdp
            if idx > 0:
                session_cdp = await _prepare_target_for_screenshot(browser, target_id) or cdp
            raw = await _capture_via_cdp(
                session_cdp,
                full_page=full_page,
                jpeg_quality=jpeg_quality,
                from_surface=from_surface,
                timeout_sec=budget,
            )
            path_label = 'window' if not from_surface else 'compositor'
            _browser_trace(
                f'screenshot done via {path_label} in '
                f'{(time.monotonic() - started_at) * 1000:.0f}ms'
            )
            return raw, None
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            if first_error is None:
                first_error = exc
            _browser_trace(
                f'screenshot: fromSurface={from_surface} failed ({type(exc).__name__}); '
                'trying alternate path'
            )

    raw = await _capture_via_browser_session(
        browser,
        full_page=full_page,
        jpeg_quality=jpeg_quality,
        timeout_sec=fallback_budget,
    )
    if raw:
        _browser_trace(
            f'screenshot done via browser.take_screenshot in '
            f'{(time.monotonic() - started_at) * 1000:.0f}ms'
        )
        return raw, None

    return None, self._screenshot_failure_error(
        cmd,
        started_at=started_at,
        first_error=first_error,
        retry_error=RuntimeError('browser.take_screenshot fallback returned no data'),
    )


async def _execute_screenshot_body(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
    browser = await self._ensure_session()
    full_page = bool(params.get('full_page', False))
    inject_image = bool(params.get('inject_image', True))
    jpeg_quality = 80
    total_budget = BROWSER_SCREENSHOT_TIMEOUT_SEC
    primary_budget = max(8.0, total_budget * 0.4)
    retry_budget = max(8.0, total_budget * 0.35)
    fallback_budget = max(6.0, total_budget * 0.25)

    started_at = time.monotonic()
    target_id = _resolve_page_target_id(browser)
    _browser_trace(
        f'screenshot begin target={str(target_id)[:8]} full_page={full_page} '
        f'budget={primary_budget:.0f}+{retry_budget:.0f}+{fallback_budget:.0f}s'
    )
    await _focus_page_target(browser, target_id)
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
        fallback_budget=fallback_budget,
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


async def execute_screenshot_impl(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
    try:
        return await asyncio.wait_for(
            _execute_screenshot_body(self, cmd, params),
            timeout=BROWSER_SCREENSHOT_TIMEOUT_SEC + 3.0,
        )
    except TimeoutError:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    f'ERROR: Browser screenshot timed out after {BROWSER_SCREENSHOT_TIMEOUT_SEC:.0f}s '
                    '(with compositor/window/fallback retries). '
                    'Try ``browser snapshot`` for DOM state, or ``browser navigate`` to reset the tab.'
                )
            ),
        )
