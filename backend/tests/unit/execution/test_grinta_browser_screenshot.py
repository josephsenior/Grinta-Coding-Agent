"""Tests for the screenshot path in GrintaNativeBrowser.

The screenshot command delegates to ``browser.take_screenshot()`` (browser-use's
built-in), which handles CDP session management and focus validation internally.
These tests verify the wrapper logic: timeout enforcement, base64 injection,
and error handling. Screenshots are inline base64 — no disk persistence.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import types
from typing import Any

import pytest

if 'browser_use' not in sys.modules:
    stub = types.ModuleType('browser_use')
    stub.Browser = object  # type: ignore[attr-defined]
    sys.modules['browser_use'] = stub

from backend.execution.browser import grinta_browser as gb  # noqa: E402
from backend.ledger.observation import (  # noqa: E402
    BrowserScreenshotObservation,
    ErrorObservation,
)
from backend.ledger.serialization.event import (  # noqa: E402
    event_from_dict,
    event_to_dict,
)


class _FakeBrowser:
    """Minimal browser stub that implements ``take_screenshot``."""

    def __init__(
        self,
        *,
        screenshot_data: bytes | None = b'PNGDATA',
        raise_exc: Exception | None = None,
    ) -> None:
        self._screenshot_data = screenshot_data
        self._raise_exc = raise_exc
        self.take_screenshot_calls: list[dict[str, Any]] = []

    async def take_screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
        format: str = 'png',
        quality: int | None = None,
    ) -> bytes:
        self.take_screenshot_calls.append(
            {'path': path, 'full_page': full_page, 'format': format, 'quality': quality}
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._screenshot_data is None:
            return b''
        return self._screenshot_data


def _assert_screenshot_result(
    obs: BrowserScreenshotObservation,
    browser: _FakeBrowser,
    *,
    full_page: bool = False,
) -> None:
    assert 'Screenshot captured' in obs.content
    assert obs.image_b64
    assert browser.take_screenshot_calls, 'take_screenshot was never called'
    call = browser.take_screenshot_calls[0]
    assert call['format'] == 'jpeg'
    assert call['quality'] == 80
    assert call['full_page'] is full_page
    decoded = base64.b64decode(obs.image_b64)
    assert decoded == b'PNGDATA'


@pytest.mark.asyncio
async def test_screenshot_returns_image_on_success() -> None:
    browser = _FakeBrowser()
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {})

    assert isinstance(obs, BrowserScreenshotObservation), getattr(obs, 'content', obs)
    _assert_screenshot_result(obs, browser)


@pytest.mark.asyncio
async def test_screenshot_full_page_passes_through() -> None:
    browser = _FakeBrowser()
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {'full_page': True})

    assert isinstance(obs, BrowserScreenshotObservation), getattr(obs, 'content', obs)
    _assert_screenshot_result(obs, browser, full_page=True)


@pytest.mark.asyncio
async def test_screenshot_inject_image_false_omits_b64() -> None:
    browser = _FakeBrowser()
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {'inject_image': False})

    assert isinstance(obs, BrowserScreenshotObservation)
    assert obs.image_b64 == ''
    assert obs.inject_skipped_reason == 'inject_image=false'


def test_screenshot_observation_round_trips_through_event_serialization() -> None:
    obs = BrowserScreenshotObservation(
        content='Screenshot captured (3 bytes)',
        image_b64=base64.b64encode(b'ABC').decode('ascii'),
        image_mime='image/jpeg',
        truncation_strategy='tail_heavy',
    )

    restored = event_from_dict(event_to_dict(obs))

    assert isinstance(restored, BrowserScreenshotObservation)
    assert restored.content == obs.content
    assert restored.image_b64 == obs.image_b64
    assert restored.truncation_strategy == 'tail_heavy'


@pytest.mark.asyncio
async def test_screenshot_returns_error_on_failure() -> None:
    browser = _FakeBrowser(raise_exc=RuntimeError('page wedged'))
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {})

    assert isinstance(obs, ErrorObservation), obs
    assert 'RuntimeError' in obs.content


@pytest.mark.asyncio
async def test_screenshot_returns_error_on_no_data() -> None:
    browser = _FakeBrowser(screenshot_data=None)
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {})

    assert isinstance(obs, ErrorObservation), obs
    assert 'no data' in obs.content.lower()


@pytest.mark.asyncio
async def test_screenshot_timeout_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.execution.browser._browser_snapshot as snap_mod

    monkeypatch.setattr(snap_mod, 'BROWSER_SCREENSHOT_TIMEOUT_SEC', 2.0)

    class _SlowBrowser(_FakeBrowser):
        async def take_screenshot(
            self,
            path: str | None = None,
            full_page: bool = False,
            format: str = 'png',
            quality: int | None = None,
        ) -> bytes:
            await asyncio.sleep(100)
            return b''

    browser = _SlowBrowser()
    shot_tool = gb.GrintaNativeBrowser()
    shot_tool._session = browser

    obs = await asyncio.wait_for(
        shot_tool.execute('screenshot', {}),
        timeout=15,
    )

    assert isinstance(obs, ErrorObservation), obs
    assert 'TimeoutError' in obs.content


if __name__ == '__main__':  # pragma: no cover
    asyncio.run(test_screenshot_returns_image_on_success())
