"""Tests for the robust screenshot path in GrintaNativeBrowser.

The goals of these tests are:

- ``_resolve_page_target_id`` must prefer focused page targets, fall back to
  the last page target when focus is on an iframe/worker, and never return
  None as long as *some* page target exists.
- ``_capture_via_cdp`` must call ``Page.captureScreenshot`` with the fast
  Windows-reliable parameter set (jpeg + optimizeForSpeed + explicit
  fromSurface), and ``from_surface=False`` must be honored for the retry
  path.
- The high-level ``screenshot`` command must retry with ``fromSurface=False``
  when the compositor path fails and still return a ``CmdOutputObservation``
  with the saved file path.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# ``browser_use`` is an optional dependency (only used at runtime through
# ``GrintaNativeBrowser._ensure_session``). The helpers under test never need
# it, so a stub keeps the import from failing on slim test environments.
if 'browser_use' not in sys.modules:
    stub = types.ModuleType('browser_use')
    stub.Browser = object  # type: ignore[attr-defined]
    sys.modules['browser_use'] = stub

from backend.execution.browser import grinta_browser as gb  # noqa: E402
from backend.ledger.observation import (  # noqa: E402
    CmdOutputObservation,
    ErrorObservation,
)


class _FakeTarget:
    def __init__(self, target_id: str, target_type: str) -> None:
        self.target_id = target_id
        self.target_type = target_type


class _SharedMockState:
    """Shared log + counters so preflight/capture see one sequence of events."""

    def __init__(self, fail_first_capture: bool = False) -> None:
        self.log: list[tuple[str, Any]] = []
        self.fail_first_capture = fail_first_capture
        self.capture_calls = 0


class _FakeCall:
    def __init__(self, state: _SharedMockState, name: str) -> None:
        self._state = state
        self._name = name

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._state.log.append((self._name, kwargs.get('params')))
        if self._name == 'captureScreenshot':
            self._state.capture_calls += 1
            if self._state.capture_calls == 1 and self._state.fail_first_capture:
                raise RuntimeError('fake compositor error')
            return {'data': base64.b64encode(b'PNGDATA').decode()}
        return {}


class _FakePage:
    def __init__(self, state: _SharedMockState) -> None:
        self._state = state

    def __getattr__(self, name: str) -> _FakeCall:
        return _FakeCall(self._state, name)


class _FakeCDPClient:
    def __init__(self, state: _SharedMockState) -> None:
        self._page = _FakePage(state)

    @property
    def send(self) -> '_FakeCDPClient':
        return self

    @property
    def Page(self) -> _FakePage:  # noqa: N802 — CDP naming
        return self._page


def _assert_retry_screenshot_result(
    obs: CmdOutputObservation,
    state: _SharedMockState,
    tmp_path: Path,
) -> None:
    assert 'Screenshot saved to' in obs.content
    assert obs.content.strip().endswith('.jpg (7 bytes)')

    capture_params = [p for name, p in state.log if name == 'captureScreenshot']
    assert [(params['fromSurface'], params['quality']) for params in capture_params] == [
        (True, 80),
        (False, 80),
    ]

    saved = list(tmp_path.glob('browser_*.jpg'))
    assert len(saved) == 1, saved
    assert saved[0].read_bytes() == b'PNGDATA'


class _FakeCDPSession:
    def __init__(self, state: _SharedMockState) -> None:
        self.cdp_client = _FakeCDPClient(state)
        self.session_id = 'sess-1'


class _FakeBrowser:
    def __init__(
        self,
        state: _SharedMockState,
        *,
        focused_type: str = 'page',
        page_targets: tuple[str, ...] = ('t-page-1',),
    ) -> None:
        self._state = state
        self._focused_type = focused_type
        self._page_targets = page_targets
        self.agent_focus_target_id = page_targets[0] if page_targets else None

    def get_focused_target(self) -> _FakeTarget | None:
        if not self._page_targets:
            return None
        return _FakeTarget(self._page_targets[0], self._focused_type)

    def get_page_targets(self) -> list[_FakeTarget]:
        return [_FakeTarget(tid, 'page') for tid in self._page_targets]

    async def get_or_create_cdp_session(
        self, target_id: str | None = None, focus: bool = True
    ) -> _FakeCDPSession:
        self._state.log.append(
            ('get_or_create_cdp_session', {'target_id': target_id, 'focus': focus})
        )
        return _FakeCDPSession(self._state)


def test_resolve_page_target_prefers_focused_page() -> None:
    state = _SharedMockState()
    browser = _FakeBrowser(
        state, focused_type='page', page_targets=('t-page-1', 't-page-2')
    )
    assert gb._resolve_page_target_id(browser) == 't-page-1'


def test_resolve_page_target_falls_back_when_focus_is_iframe() -> None:
    state = _SharedMockState()
    browser = _FakeBrowser(
        state, focused_type='iframe', page_targets=('t-page-1', 't-page-2')
    )
    # Focused target is not a page → fall back to last page in the list.
    assert gb._resolve_page_target_id(browser) == 't-page-2'


def test_resolve_page_target_returns_agent_focus_when_no_pages() -> None:
    state = _SharedMockState()
    browser = _FakeBrowser(state, focused_type='iframe', page_targets=())
    browser.agent_focus_target_id = 't-unknown'
    assert gb._resolve_page_target_id(browser) == 't-unknown'


@pytest.mark.asyncio
async def test_capture_via_cdp_uses_fast_windows_reliable_params() -> None:
    state = _SharedMockState()
    cdp = _FakeCDPSession(state)
    raw = await gb._capture_via_cdp(
        cdp,
        full_page=False,
        jpeg_quality=80,
        from_surface=True,
        timeout_sec=2.0,
    )
    assert raw == b'PNGDATA'
    capture_calls = [p for name, p in state.log if name == 'captureScreenshot']
    assert capture_calls == [
        {
            'format': 'jpeg',
            'quality': 80,
            'captureBeyondViewport': False,
            'optimizeForSpeed': True,
            'fromSurface': True,
        }
    ]


@pytest.mark.asyncio
async def test_capture_via_cdp_full_page_and_from_surface_false() -> None:
    state = _SharedMockState()
    cdp = _FakeCDPSession(state)
    await gb._capture_via_cdp(
        cdp,
        full_page=True,
        jpeg_quality=60,
        from_surface=False,
        timeout_sec=2.0,
    )
    params = [p for name, p in state.log if name == 'captureScreenshot'][0]
    assert params['captureBeyondViewport'] is True
    assert params['fromSurface'] is False
    assert params['quality'] == 60


@pytest.mark.asyncio
async def test_screenshot_retries_with_from_surface_false_on_failure(
    tmp_path: Path,
) -> None:
    state = _SharedMockState(fail_first_capture=True)
    browser = _FakeBrowser(state)

    shot_tool = gb.GrintaNativeBrowser(tmp_path)
    shot_tool._session = browser  # skip real browser-use startup

    obs = await shot_tool.execute('screenshot', {})

    assert isinstance(obs, CmdOutputObservation), getattr(obs, 'content', obs)
    _assert_retry_screenshot_result(obs, state, tmp_path)


@pytest.mark.asyncio
async def test_screenshot_returns_error_when_both_paths_fail(
    tmp_path: Path,
) -> None:
    class _AlwaysFailCall(_FakeCall):
        async def __call__(self, *args: Any, **kwargs: Any) -> Any:
            self._state.log.append((self._name, kwargs.get('params')))
            if self._name == 'captureScreenshot':
                raise RuntimeError('page wedged')
            return {}

    class _AlwaysFailPage(_FakePage):
        def __getattr__(self, name: str) -> _AlwaysFailCall:
            return _AlwaysFailCall(self._state, name)

    class _AlwaysFailCDPClient(_FakeCDPClient):
        def __init__(self, state: _SharedMockState) -> None:
            self._page = _AlwaysFailPage(state)

    class _AlwaysFailCDPSession(_FakeCDPSession):
        def __init__(self, state: _SharedMockState) -> None:
            self.cdp_client = _AlwaysFailCDPClient(state)
            self.session_id = 'sess-err'

    class _AlwaysFailBrowser(_FakeBrowser):
        async def get_or_create_cdp_session(
            self, target_id: str | None = None, focus: bool = True
        ) -> _AlwaysFailCDPSession:
            self._state.log.append(
                ('get_or_create_cdp_session', {'target_id': target_id, 'focus': focus})
            )
            return _AlwaysFailCDPSession(self._state)

    state = _SharedMockState()
    browser = _AlwaysFailBrowser(state)
    shot_tool = gb.GrintaNativeBrowser(tmp_path)
    shot_tool._session = browser

    obs = await shot_tool.execute('screenshot', {})

    assert isinstance(obs, ErrorObservation), obs
    assert 'compositor' in obs.content or 'window capture' in obs.content
    assert list(tmp_path.glob('browser_*.jpg')) == []


@pytest.mark.asyncio
async def test_prepare_target_runs_page_enable_and_dialog_dismiss(
    tmp_path: Path,
) -> None:
    state = _SharedMockState()
    browser = _FakeBrowser(state)
    cdp = await gb._prepare_target_for_screenshot(browser, 't-page-1')
    assert cdp is not None
    names = [name for name, _ in state.log]
    assert 'get_or_create_cdp_session' in names
    assert 'enable' in names
    assert 'bringToFront' in names
    assert 'handleJavaScriptDialog' in names


@pytest.mark.asyncio
async def test_prepare_target_returns_none_on_cdp_failure(tmp_path: Path) -> None:
    class _FailingBrowser(_FakeBrowser):
        async def get_or_create_cdp_session(
            self, target_id: str | None = None, focus: bool = True
        ) -> _FakeCDPSession:
            raise RuntimeError('no session')

    state = _SharedMockState()
    browser = _FailingBrowser(state)
    cdp = await gb._prepare_target_for_screenshot(browser, 't-page-1')
    assert cdp is None


if __name__ == '__main__':  # pragma: no cover
    asyncio.run(test_prepare_target_runs_page_enable_and_dialog_dismiss(Path('.')))
