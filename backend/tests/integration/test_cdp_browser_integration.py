"""Drives a real Chromium over CDP through the agent-facing browser tool.

Skipped when no Chromium-family browser is installed. The fixture page is
served over http from a temp directory: ``data:`` URLs are rejected by the
tool's URL validation, and live third-party sites make assertions flaky.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import socket
import threading

import pytest

from backend.execution.browser._cdp_engine import find_browser_binary
from backend.execution.browser.grinta_browser import GrintaNativeBrowser

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        find_browser_binary() is None,
        reason='no Chromium-based browser installed',
    ),
    # Keep every test in this file on one xdist worker. Each test launches its
    # own Chrome process; on shared/constrained CI hardware (notably macOS
    # runners under -n 2) two workers launching Chrome at once can starve both
    # of CPU and make an in-flight CDP call time out. Serializing relative to
    # other files in this module is enough — no event-loop-scope change needed.
    pytest.mark.xdist_group(name='cdp-browser'),
]

FIXTURE_HTML = (
    '<!doctype html><html><body>'
    '<h1>Grinta browser fixture</h1>'
    '<p>hello world paragraph</p>'
    '<a href="/second.html">go to second</a>'
    '<input id=t type=text placeholder="your name">'
    '<select id=s><option value=a>Alpha</option><option value=b>Beta</option></select>'
    '<input id=f type=file>'
    "<button onclick=\"document.getElementById('out').textContent='clicked!'\">"
    'press me</button>'
    '<div id=out></div>'
    '<div style="height:3000px"></div>'
    '<p>bottom marker</p>'
    '</body></html>'
)

SECOND_HTML = '<!doctype html><html><body><h1>second page</h1></body></html>'


@pytest.fixture(scope='module')
def fixture_site(tmp_path_factory) -> str:
    """Serve the fixture pages on a loopback port; return the index URL."""
    directory = tmp_path_factory.mktemp('grinta-cdp-www')
    (directory / 'index.html').write_text(FIXTURE_HTML, encoding='utf-8')
    (directory / 'second.html').write_text(SECOND_HTML, encoding='utf-8')

    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(directory)
    )
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}/index.html'
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
async def browser(tmp_path):
    session = GrintaNativeBrowser(workspace_root=str(tmp_path))
    try:
        yield session
    finally:
        await session.shutdown()


def _indices(snapshot: str) -> dict[str, int]:
    """Map each ``[n]<tag>label`` line to its index, keyed by the whole line."""
    out: dict[str, int] = {}
    for line in snapshot.splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            out[stripped] = int(stripped.split(']')[0][1:])
    return out


def _index_for(snapshot: str, fragment: str) -> int:
    for line, index in _indices(snapshot).items():
        if fragment in line:
            return index
    raise AssertionError(f'{fragment!r} not in snapshot:\n{snapshot}')


async def test_navigate_and_snapshot_lists_interactive_elements(
    browser, fixture_site
) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    obs = await browser.execute('snapshot', {'mode': 'interactive'})
    snapshot = str(obs.content)

    assert '<a>' in snapshot
    assert '<input type=text>' in snapshot
    assert '<select>' in snapshot
    assert '<button>' in snapshot


async def test_full_snapshot_includes_page_prose(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    obs = await browser.execute('snapshot', {'mode': 'full'})
    assert 'hello world paragraph' in str(obs.content)


async def test_click_by_index_runs_the_page_handler(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)

    await browser.execute('click', {'index': _index_for(snapshot, 'press me')})

    result = await browser._session.evaluate(
        'document.getElementById("out").textContent'
    )
    assert result == 'clicked!'


async def test_type_by_index_sets_the_field_value(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)

    index = _index_for(snapshot, '<input type=text>')
    await browser.execute('type', {'index': index, 'text': 'Youssef'})

    assert await browser._session.evaluate('document.getElementById("t").value') == (
        'Youssef'
    )


async def test_select_dropdown_option(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)

    await browser.execute(
        'select_dropdown_option',
        {'index': _index_for(snapshot, '<select>'), 'option_text': 'Beta'},
    )

    assert await browser._session.evaluate('document.getElementById("s").value') == 'b'


async def test_click_link_navigates_and_go_back_returns(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)

    await browser.execute('click', {'index': _index_for(snapshot, 'go to second')})
    await asyncio.sleep(0.5)
    assert 'second' in await browser._session.current_url()

    await browser.execute('go_back', {})
    await asyncio.sleep(0.5)
    assert 'index.html' in await browser._session.current_url()


async def test_scroll_and_scroll_to_text(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    assert await browser._session.evaluate('window.scrollY') == 0

    await browser.execute('scroll', {'direction': 'down', 'pixels': 500})
    await asyncio.sleep(0.3)
    assert await browser._session.evaluate('window.scrollY') > 0

    obs = await browser.execute('scroll', {'to_text': 'bottom marker'})
    assert 'Scrolled to text' in str(obs.content)


async def test_screenshot_returns_image_bytes(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    obs = await browser.execute('screenshot', {'inject_image': False})
    assert 'Screenshot captured' in str(obs.content)


async def test_tab_lifecycle(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    await browser.execute('navigate', {'url': fixture_site, 'new_tab': True})
    await asyncio.sleep(0.5)  # target creation is asynchronous browser-side

    tabs = await browser._session.page_targets()
    assert len(tabs) == 2

    assert 'Switched' in str(
        (await browser.execute('switch_tab', {'index': 0})).content
    )
    assert 'Closed' in str((await browser.execute('close_tab', {'index': 1})).content)
    assert len(await browser._session.page_targets()) == 1


async def test_upload_file_sets_the_input(browser, fixture_site, tmp_path) -> None:
    upload = tmp_path / 'payload.txt'
    upload.write_text('data', encoding='utf-8')
    await browser.execute('navigate', {'url': fixture_site})
    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)

    obs = await browser.execute(
        'upload_file',
        {'index': _index_for(snapshot, 'type=file'), 'path': 'payload.txt'},
    )

    assert 'Uploaded' in str(obs.content)
    assert (
        await browser._session.evaluate('document.getElementById("f").files.length')
        == 1
    )


async def test_stale_index_reports_a_clear_error(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    obs = await browser.execute('click', {'index': 9999})
    assert type(obs).__name__ == 'ErrorObservation'
    assert 'No element at index' in str(obs.content)


async def test_non_http_urls_are_refused(browser) -> None:
    obs = await browser.execute('navigate', {'url': 'file:///etc/passwd'})
    assert type(obs).__name__ == 'ErrorObservation'
    assert 'http and https' in str(obs.content)


ADD_IFRAME_JS = """
(() => {
  const frame = document.createElement('iframe');
  frame.style.width = '400px';
  frame.style.height = '200px';
  document.body.insertBefore(frame, document.body.firstChild);
  const doc = frame.contentDocument;
  doc.body.innerHTML = '<button id=ib>inner</button>';
  doc.getElementById('ib').addEventListener('click', function () {
    this.textContent = 'IN';
  });
  return true;
})()
"""

READ_IFRAME_BUTTON_JS = """
(() => document.querySelector('iframe').contentDocument
        .getElementById('ib').textContent)()
"""


async def test_iframe_content_is_indexed_and_clickable(browser, fixture_site) -> None:
    await browser.execute('navigate', {'url': fixture_site})
    await browser._session.evaluate(ADD_IFRAME_JS)
    await asyncio.sleep(0.5)

    snapshot = str((await browser.execute('snapshot', {'mode': 'interactive'})).content)
    await browser.execute('click', {'index': _index_for(snapshot, 'inner')})
    await asyncio.sleep(0.3)

    assert await browser._session.evaluate(READ_IFRAME_BUTTON_JS) == 'IN'
