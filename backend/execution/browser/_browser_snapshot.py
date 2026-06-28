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
from backend.core.logging.logger import app_logger as logger
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


async def _execute_screenshot_body(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
    browser = await self._ensure_session()
    full_page = bool(params.get('full_page', False))
    inject_image = bool(params.get('inject_image', True))
    jpeg_quality = 80

    started_at = time.monotonic()
    logger.info(
        'browser screenshot begin (full_page=%s, budget=%.0fs)', full_page, BROWSER_SCREENSHOT_TIMEOUT_SEC
    )
    _browser_trace(
        f'screenshot begin full_page={full_page} '
        f'budget={BROWSER_SCREENSHOT_TIMEOUT_SEC:.0f}s'
    )

    try:
        raw = await asyncio.wait_for(
            browser.take_screenshot(
                path=None,
                full_page=full_page,
                format='jpeg',
                quality=jpeg_quality,
            ),
            timeout=BROWSER_SCREENSHOT_TIMEOUT_SEC,
        )
    except Exception as exc:
        total = time.monotonic() - started_at
        logger.error('browser screenshot failed after %.1fs: %s: %s', total, type(exc).__name__, exc)
        _browser_trace(f'screenshot failed: {type(exc).__name__}: {exc}')
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    f'ERROR: Browser screenshot failed after {total:.0f}s '
                    f'({type(exc).__name__}). '
                    'Try ``browser snapshot`` for DOM state, or '
                    '``browser navigate`` to the same URL to reset.'
                )
            ),
        )

    if not raw:
        _browser_trace('screenshot: take_screenshot returned no data')
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    'ERROR: Browser screenshot returned no data. '
                    'Try ``browser snapshot`` for DOM state, or '
                    '``browser navigate`` to the same URL to reset.'
                )
            ),
        )

    elapsed_ms = (time.monotonic() - started_at) * 1000
    logger.info('browser screenshot done in %.0fms (%d bytes)', elapsed_ms, len(raw))
    _browser_trace(f'screenshot done in {elapsed_ms:.0f}ms')

    name = f'browser_{uuid.uuid4().hex[:12]}.jpg'
    path = self._downloads / name
    path.write_bytes(raw)
    raw_len = len(raw)
    body = f'Screenshot saved to: {path} ({raw_len} bytes)'
    b64_payload = base64.b64encode(raw).decode('ascii')
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
        logger.error(
            'browser screenshot timed out after %.0fs', BROWSER_SCREENSHOT_TIMEOUT_SEC
        )
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=(
                    f'ERROR: Browser screenshot timed out after {BROWSER_SCREENSHOT_TIMEOUT_SEC:.0f}s. '
                    'Try ``browser snapshot`` for DOM state, or ``browser navigate`` to reset the tab.'
                )
            ),
        )
