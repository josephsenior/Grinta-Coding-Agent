"""Unit tests for the CDP engine — no browser process required.

Browser-driving coverage lives in
``backend/tests/integration/test_cdp_browser_integration.py``; these tests
pin the protocol framing, binary discovery and page-script contracts that
can be checked without launching Chromium.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.execution.browser import _cdp_engine
from backend.execution.browser._cdp_engine import (
    CDPBrowser,
    CDPConnection,
    CDPError,
    find_browser_binary,
)


class FakeSocket:
    """Minimal websocket double: records sends, replays queued responses."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self.sent: list[dict] = []
        self._responses = responses or []
        self._queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if self._responses:
            reply = dict(self._responses.pop(0))
            reply.setdefault('id', payload['id'])
            await self._queue.put(json.dumps(reply))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        return await self._queue.get()


class TestCDPConnection:
    async def test_send_returns_result_payload(self) -> None:
        sock = FakeSocket([{'result': {'targetInfos': []}}])
        conn = CDPConnection(sock)
        try:
            result = await conn.send('Target.getTargets')
            assert result == {'targetInfos': []}
            assert sock.sent[0]['method'] == 'Target.getTargets'
        finally:
            await conn.close()

    async def test_session_id_is_attached_when_given(self) -> None:
        sock = FakeSocket([{'result': {}}])
        conn = CDPConnection(sock)
        try:
            await conn.send('Page.enable', session_id='S1')
            assert sock.sent[0]['sessionId'] == 'S1'
        finally:
            await conn.close()

    async def test_no_session_id_key_when_absent(self) -> None:
        sock = FakeSocket([{'result': {}}])
        conn = CDPConnection(sock)
        try:
            await conn.send('Page.enable')
            assert 'sessionId' not in sock.sent[0]
        finally:
            await conn.close()

    async def test_message_ids_increment(self) -> None:
        sock = FakeSocket([{'result': {}}, {'result': {}}])
        conn = CDPConnection(sock)
        try:
            await conn.send('A')
            await conn.send('B')
            assert [m['id'] for m in sock.sent] == [1, 2]
        finally:
            await conn.close()

    async def test_protocol_error_raises_cdp_error(self) -> None:
        sock = FakeSocket([{'error': {'code': -32000, 'message': 'boom'}}])
        conn = CDPConnection(sock)
        try:
            with pytest.raises(CDPError, match='boom'):
                await conn.send('Page.navigate')
        finally:
            await conn.close()

    async def test_timeout_raises_cdp_error(self) -> None:
        sock = FakeSocket()  # never answers
        conn = CDPConnection(sock)
        try:
            with pytest.raises(CDPError, match='timed out'):
                await conn.send('Page.navigate', timeout_sec=0.05)
        finally:
            await conn.close()

    async def test_events_are_buffered_for_draining(self) -> None:
        sock = FakeSocket([{'result': {}}])
        conn = CDPConnection(sock)
        try:
            await sock._queue.put(
                json.dumps({'method': 'Page.loadEventFired', 'params': {'t': 1}})
            )
            await conn.send('Page.enable')  # pumps the reader
            await asyncio.sleep(0.05)
            assert conn.drain_events('Page.loadEventFired') == [{'t': 1}]
            assert conn.drain_events('Page.loadEventFired') == []
        finally:
            await conn.close()


class TestBinaryDiscovery:
    def test_env_var_wins_when_path_exists(self, tmp_path, monkeypatch) -> None:
        fake = tmp_path / 'my-chrome.exe'
        fake.write_text('', encoding='utf-8')
        monkeypatch.setenv('GRINTA_BROWSER_BINARY', str(fake))
        assert find_browser_binary() == str(fake)

    def test_env_var_ignored_when_path_missing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv('GRINTA_BROWSER_BINARY', str(tmp_path / 'nope.exe'))
        monkeypatch.setattr(_cdp_engine, '_BROWSER_CANDIDATES', ())
        monkeypatch.setattr(_cdp_engine, '_PATH_LOOKUPS', ())
        assert find_browser_binary() is None

    def test_returns_none_when_nothing_installed(self, monkeypatch) -> None:
        for var in _cdp_engine._BROWSER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(_cdp_engine, '_BROWSER_CANDIDATES', ())
        monkeypatch.setattr(_cdp_engine, '_PATH_LOOKUPS', ())
        assert find_browser_binary() is None

    def test_falls_back_to_path_lookup(self, monkeypatch) -> None:
        for var in _cdp_engine._BROWSER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(_cdp_engine, '_BROWSER_CANDIDATES', ())
        monkeypatch.setattr(_cdp_engine, '_PATH_LOOKUPS', ('chromium',))
        monkeypatch.setattr(
            _cdp_engine.shutil, 'which', lambda name: '/usr/bin/chromium'
        )
        assert find_browser_binary() == '/usr/bin/chromium'


class TestSessionGuards:
    def test_connection_property_requires_start(self) -> None:
        browser = CDPBrowser()
        assert browser.started is False
        with pytest.raises(RuntimeError, match='not running'):
            _ = browser.connection

    def test_require_session_without_focus_raises(self) -> None:
        browser = CDPBrowser()
        with pytest.raises(RuntimeError, match='No focused page'):
            browser._require_session()

    async def test_stop_is_safe_before_start(self) -> None:
        browser = CDPBrowser()
        await browser.stop()  # must not raise
        assert browser.started is False


class TestPageScripts:
    """The page-side contracts the selector map depends on."""

    def test_serializer_defines_the_shared_element_array(self) -> None:
        assert 'window.__grinta_els = []' in _cdp_engine._SERIALIZER_JS

    def test_serializer_emits_bracketed_indices(self) -> None:
        assert "lines.push('[' + i + ']<'" in _cdp_engine._SERIALIZER_JS

    def test_serializer_traverses_shadow_dom_and_frames(self) -> None:
        source = _cdp_engine._SERIALIZER_JS
        assert 'shadowRoot' in source
        assert 'contentDocument' in source
        assert 'cross-origin frame' in source

    def test_resolve_walks_frame_chain_for_absolute_coords(self) -> None:
        # Clicks are dispatched in top-level viewport space, so an element
        # inside an iframe must have each host frame's offset added.
        assert 'frameElement' in _cdp_engine._RESOLVE_BOX_JS

    def test_resolve_reads_the_index_the_serializer_wrote(self) -> None:
        assert 'window.__grinta_els' in _cdp_engine._RESOLVE_BOX_JS

    def test_interactive_selector_covers_core_controls(self) -> None:
        selector = _cdp_engine._INTERACTIVE_SELECTOR
        for tag in ('a[href]', 'button', 'input', 'select', 'textarea'):
            assert tag in selector
