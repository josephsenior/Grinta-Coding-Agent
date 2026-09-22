"""Chrome DevTools Protocol engine backing the native browser tool.

Replaces browser-use. Speaks CDP over a websocket to a Chromium-family
browser already installed on the machine (Chrome, Edge, Chromium, Brave),
so the browser tool costs nothing at install time: ``websockets`` is
already a Grinta dependency and everything else here is standard library.

Two design points worth knowing before editing:

**The selector map lives in the page, not in Python.** ``snapshot_text``
evaluates a serializer in the page that collects visible, interactive
elements, stashes them on ``window.__grinta_els``, and returns
``[n]<tag>label`` lines. ``click(index)`` then resolves ``n`` back through
that same array. Nothing depends on CDP node ids surviving between calls,
which is what makes indices stable across navigations without bookkeeping
on our side.

**One websocket, many sessions.** The browser-level connection multiplexes
per-target (per-tab) sessions via ``sessionId``. ``_attach`` flattens them
onto the single socket rather than opening a socket per tab.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import tempfile
import urllib.error
import urllib.request
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.execution.browser._browser_shared import _browser_trace

# Chromium-family binaries, most-preferred first. Chrome and Edge cover
# effectively every developer machine; Edge ships with Windows.
_BROWSER_ENV_VARS = ('GRINTA_BROWSER_BINARY', 'CHROME_PATH', 'BROWSER_PATH')

_BROWSER_CANDIDATES: tuple[str, ...] = (
    # Windows
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
    # macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    # Linux
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/microsoft-edge',
    '/snap/bin/chromium',
)

_PATH_LOOKUPS: tuple[str, ...] = (
    'google-chrome',
    'google-chrome-stable',
    'chromium',
    'chromium-browser',
    'microsoft-edge',
    'chrome',
)

_INSTALL_HINT = (
    'No Chromium-based browser found. Install Google Chrome, Microsoft Edge, '
    'Chromium or Brave, or point GRINTA_BROWSER_BINARY at the executable.'
)

# Elements the agent can act on. Kept deliberately broad: missing an element
# is worse than listing an inert one, since the agent can simply not use it.
_INTERACTIVE_SELECTOR = (
    'a[href],button,input,select,textarea,summary,label,'
    '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],'
    '[role=menuitem],[role=option],[role=switch],[role=textbox],'
    '[onclick],[contenteditable=""],[contenteditable=true],[tabindex]'
)

# Serializer: assigns indices, stashes nodes on window, returns text lines.
# Shadow roots and same-origin iframes are traversed. A cross-origin iframe
# cannot be read from page script, so it is listed as a single entry telling
# the agent to navigate to its src directly.
_SERIALIZER_JS = """
(() => {
  const SEL = %s;
  const lines = [];
  window.__grinta_els = [];

  const visible = (el, win) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    if (r.bottom < 0 || r.top > win.innerHeight) return null;
    if (r.right < 0 || r.left > win.innerWidth) return null;
    const st = win.getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return null;
    if (parseFloat(st.opacity || '1') === 0) return null;
    return r;
  };

  const label = (el) => {
    let t = el.getAttribute('aria-label') || '';
    if (!t && el.tagName === 'INPUT') {
      t = el.getAttribute('placeholder') || el.value || '';
    }
    if (!t) t = (el.innerText || el.textContent || '').trim();
    if (!t) t = el.getAttribute('title') || el.getAttribute('name') || '';
    return String(t).replace(/\\s+/g, ' ').trim().slice(0, 120);
  };

  const push = (el, win, extra) => {
    const i = window.__grinta_els.length;
    window.__grinta_els.push(el);
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type');
    const checked = el.checked === true ? ' checked' : '';
    lines.push('[' + i + ']<' + tag + (type ? ' type=' + type : '') +
               checked + '>' + (extra || label(el)));
  };

  const walk = (root, win, depth) => {
    if (depth > 5) return;
    let nodes;
    try { nodes = root.querySelectorAll(SEL); } catch (e) { return; }
    for (const el of nodes) {
      if (el.disabled) continue;
      if (el.getAttribute('aria-hidden') === 'true') continue;
      if (!visible(el, win)) continue;
      push(el, win);
    }
    let all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of all) {
      if (el.shadowRoot) walk(el.shadowRoot, win, depth + 1);
      if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
        if (!visible(el, win)) continue;
        let doc = null;
        try { doc = el.contentDocument; } catch (e) { doc = null; }
        if (doc && doc.documentElement) {
          walk(doc, el.contentWindow, depth + 1);
        } else {
          push(el, win, 'cross-origin frame, navigate to: ' +
               (el.getAttribute('src') || 'unknown'));
        }
      }
    }
  };

  walk(document, window, 0);
  return lines.join('\\n');
})()
""" % json.dumps(_INTERACTIVE_SELECTOR)

# Full readable page text, used by snapshot mode=full and extract.
_PAGE_TEXT_JS = """
(() => {
  const t = document.body ? (document.body.innerText || '') : '';
  return (document.title ? document.title + '\\n\\n' : '') + t;
})()
"""

# Coordinates must be in TOP-level viewport space for Input.dispatchMouseEvent,
# but an element inside an iframe reports a rect relative to that frame. Walk
# the frame chain and add each host frame's offset.
_RESOLVE_BOX_JS = """
(() => {
  const el = (window.__grinta_els || [])[%d];
  if (!el) return null;
  try { el.scrollIntoView({block: 'center', inline: 'center'}); } catch (e) {}
  const r = el.getBoundingClientRect();
  let x = r.left + r.width / 2;
  let y = r.top + r.height / 2;
  let win = el.ownerDocument ? el.ownerDocument.defaultView : null;
  let hops = 0;
  while (win && win !== window && win.frameElement && hops++ < 10) {
    const fr = win.frameElement.getBoundingClientRect();
    x += fr.left;
    y += fr.top;
    win = win.parent;
  }
  return JSON.stringify({
    x: x,
    y: y,
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || ''
  });
})()
"""


def find_browser_binary() -> str | None:
    """Return a Chromium-family executable, or None when none is installed."""
    for var in _BROWSER_ENV_VARS:
        candidate = os.environ.get(var, '').strip()
        if candidate and os.path.exists(candidate):
            return candidate
    for path in _BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
    for name in _PATH_LOOKUPS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


class CDPError(RuntimeError):
    """A CDP command returned an error payload."""


class CDPConnection:
    """One websocket to the browser, multiplexing per-target sessions."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._reader: asyncio.Task | None = asyncio.create_task(
            self._read_loop(), name='grinta-cdp-reader'
        )

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                mid = msg.get('id')
                if mid is not None:
                    future = self._pending.pop(mid, None)
                    if future is not None and not future.done():
                        future.set_result(msg)
                    continue
                method = msg.get('method')
                if method:
                    self._events.setdefault(method, []).append(msg.get('params', {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # connection closed or malformed frame
            logger.debug('CDP read loop ended: %s', exc)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CDPError('CDP connection closed'))
            self._pending.clear()

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> dict[str, Any]:
        """Issue a CDP command and await its result."""
        self._next_id += 1
        message_id = self._next_id
        payload: dict[str, Any] = {
            'id': message_id,
            'method': method,
            'params': params or {},
        }
        if session_id:
            payload['sessionId'] = session_id

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        await self._ws.send(json.dumps(payload))
        try:
            msg = await asyncio.wait_for(future, timeout=timeout_sec)
        except TimeoutError:
            self._pending.pop(message_id, None)
            raise CDPError(f'{method} timed out after {timeout_sec:.0f}s') from None
        if 'error' in msg:
            raise CDPError(f'{method} failed: {msg["error"]}')
        return msg.get('result', {})

    def drain_events(self, method: str) -> list[dict[str, Any]]:
        """Pop buffered events for *method* (used for load/lifecycle waits)."""
        return self._events.pop(method, [])

    async def close(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self._ws.close()
        except Exception as exc:
            logger.debug('CDP socket close: %s', exc)


class CDPBrowser:
    """A launched browser plus the page operations the browser tool needs."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._process: asyncio.subprocess.Process | None = None
        self._profile_dir: str | None = None
        self._conn: CDPConnection | None = None
        self._session_by_target: dict[str, str] = {}
        self.focused_target_id: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self, *, timeout_sec: float = 45.0) -> None:
        """Launch the browser and attach to its first page target."""
        binary = find_browser_binary()
        if binary is None:
            raise RuntimeError(_INSTALL_HINT)

        port = _free_port()
        self._profile_dir = tempfile.mkdtemp(prefix='grinta-browser-')
        argv = [
            binary,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={self._profile_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-background-networking',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=Translate,OptimizationHints',
            '--disable-gpu',
            'about:blank',
        ]
        if self._headless:
            # Classic headless, not --headless=new: the new mode shares
            # headed Chrome's compositor path, which can stall Runtime.evaluate
            # and Page.captureScreenshot indefinitely on GPU-less CI runners
            # (observed hanging past a 45s budget on macOS GitHub Actions
            # runners specifically, while Linux/Windows CI and local runs were
            # fine) since there's never a real frame for it to wait on.
            argv.insert(1, '--headless')

        _browser_trace(f'launching {os.path.basename(binary)} on port {port}')
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        ws_url = await self._await_devtools_endpoint(port, timeout_sec=timeout_sec)
        import websockets

        ws = await websockets.connect(ws_url, max_size=100 * 1024 * 1024)
        self._conn = CDPConnection(ws)
        await self._attach_to_first_page()
        _browser_trace('browser session ready')

    async def _await_devtools_endpoint(self, port: int, *, timeout_sec: float) -> str:
        """Poll /json/version until the browser exposes its websocket URL."""
        deadline = asyncio.get_running_loop().time() + timeout_sec
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise RuntimeError(
                    f'Browser exited during startup (code {self._process.returncode}).'
                )
            try:
                return await asyncio.to_thread(self._read_ws_url, port)
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        raise RuntimeError(
            f'Browser did not expose a CDP endpoint within {timeout_sec:.0f}s '
            f'({last_error}). Check antivirus or sandbox restrictions.'
        )

    @staticmethod
    def _read_ws_url(port: int) -> str:
        with urllib.request.urlopen(
            f'http://127.0.0.1:{port}/json/version', timeout=2
        ) as response:
            return str(json.load(response)['webSocketDebuggerUrl'])

    async def _attach_to_first_page(self) -> None:
        for _ in range(50):
            targets = await self.page_targets()
            if targets:
                await self.attach(targets[0]['targetId'])
                return
            await asyncio.sleep(0.1)
        raise RuntimeError('Browser started but exposed no page target.')

    async def stop(self) -> None:
        """Close the connection, kill the browser, remove the temp profile."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
            except (TimeoutError, ProcessLookupError, OSError):
                with contextlib.suppress(ProcessLookupError, OSError):
                    process.kill()
        if self._profile_dir:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None
        self._session_by_target.clear()
        self.focused_target_id = None

    # ── plumbing ─────────────────────────────────────────────────────

    @property
    def connection(self) -> CDPConnection:
        if self._conn is None:
            raise RuntimeError('Browser session is not running; call start first.')
        return self._conn

    @property
    def started(self) -> bool:
        return self._conn is not None

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> dict[str, Any]:
        """Raw CDP escape hatch, scoped to the focused page by default."""
        return await self.connection.send(
            method, params, session_id=session_id, timeout_sec=timeout_sec
        )

    async def page_send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_sec: float = 30.0,
    ) -> dict[str, Any]:
        """Send a command to the focused page target."""
        return await self.connection.send(
            method, params, session_id=self._require_session(), timeout_sec=timeout_sec
        )

    def _require_session(self) -> str:
        target_id = self.focused_target_id
        session_id = self._session_by_target.get(target_id or '')
        if not session_id:
            raise RuntimeError(
                'No focused page; call start or navigate on a running session.'
            )
        return session_id

    async def attach(self, target_id: str) -> str:
        """Attach to *target_id* (idempotent) and make it the focused page."""
        session_id = self._session_by_target.get(target_id)
        if session_id is None:
            result = await self.connection.send(
                'Target.attachToTarget', {'targetId': target_id, 'flatten': True}
            )
            session_id = str(result['sessionId'])
            self._session_by_target[target_id] = session_id
            for domain in ('Page', 'Runtime', 'DOM'):
                await self.connection.send(f'{domain}.enable', session_id=session_id)
        self.focused_target_id = target_id
        return session_id

    async def evaluate(self, expression: str, *, timeout_sec: float = 45.0) -> Any:
        """Evaluate JS in the focused page and return the value by value."""
        result = await self.page_send(
            'Runtime.evaluate',
            {
                'expression': expression,
                'returnByValue': True,
                'awaitPromise': True,
            },
            timeout_sec=timeout_sec,
        )
        details = result.get('exceptionDetails')
        if details:
            text = details.get('exception', {}).get('description') or details.get(
                'text'
            )
            raise CDPError(f'Page script error: {text}')
        return result.get('result', {}).get('value')

    # ── tabs ─────────────────────────────────────────────────────────

    async def page_targets(self) -> list[dict[str, Any]]:
        """Page targets in browser order, newest last."""
        result = await self.connection.send('Target.getTargets')
        return [
            info for info in result.get('targetInfos', []) if info.get('type') == 'page'
        ]

    async def new_tab(self, url: str = 'about:blank') -> str:
        result = await self.connection.send('Target.createTarget', {'url': url})
        target_id = str(result['targetId'])
        await self.attach(target_id)
        return target_id

    async def close_tab(self, target_id: str) -> None:
        """Close a tab and wait for the browser to actually drop the target.

        ``Target.closeTarget`` acknowledges before teardown completes, so a
        caller that immediately lists tabs would still see the closed one.
        """
        await self.connection.send('Target.closeTarget', {'targetId': target_id})
        self._session_by_target.pop(target_id, None)

        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            remaining = await self.page_targets()
            if all(page['targetId'] != target_id for page in remaining):
                break
            await asyncio.sleep(0.05)

        if self.focused_target_id == target_id:
            self.focused_target_id = None
            remaining = await self.page_targets()
            if remaining:
                await self.attach(remaining[0]['targetId'])

    # ── navigation ───────────────────────────────────────────────────

    async def navigate(
        self, url: str, *, new_tab: bool = False, timeout_sec: float = 30.0
    ) -> None:
        if new_tab:
            await self.new_tab(url)
        else:
            result = await self.page_send(
                'Page.navigate',
                {'url': url, 'transitionType': 'address_bar'},
                timeout_sec=timeout_sec,
            )
            if result.get('errorText'):
                raise RuntimeError(f'Navigation failed: {result["errorText"]}')
        await self.wait_for_load(timeout_sec=timeout_sec)

    async def go_back(self, *, timeout_sec: float = 30.0) -> None:
        history = await self.page_send('Page.getNavigationHistory')
        index = int(history.get('currentIndex', 0))
        entries = history.get('entries', [])
        if index <= 0 or not entries:
            raise RuntimeError('No previous page in this tab.')
        await self.page_send(
            'Page.navigateToHistoryEntry',
            {'entryId': entries[index - 1]['id']},
            timeout_sec=timeout_sec,
        )
        await self.wait_for_load(timeout_sec=timeout_sec)

    async def wait_for_load(self, *, timeout_sec: float = 30.0) -> None:
        """Wait until document.readyState is complete (best effort)."""
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self.evaluate('document.readyState', timeout_sec=5)
            except Exception:
                await asyncio.sleep(0.1)
                continue
            if state in ('interactive', 'complete'):
                return
            await asyncio.sleep(0.1)

    async def current_url(self) -> str:
        try:
            return str(await self.evaluate('location.href', timeout_sec=5) or '')
        except Exception:
            return ''

    # ── page state ───────────────────────────────────────────────────

    async def snapshot_text(self, *, timeout_sec: float = 45.0) -> str:
        """Rebuild the page selector map and return indexed element lines."""
        value = await self.evaluate(_SERIALIZER_JS, timeout_sec=timeout_sec)
        return str(value or '')

    async def page_text(self, *, timeout_sec: float = 45.0) -> str:
        value = await self.evaluate(_PAGE_TEXT_JS, timeout_sec=timeout_sec)
        return str(value or '')

    async def resolve_index(self, index: int) -> dict[str, Any] | None:
        """Return {x, y, tag, type} for a snapshot index, scrolling it into view."""
        raw = await self.evaluate(_RESOLVE_BOX_JS % index)
        if not raw:
            return None
        try:
            return dict(json.loads(raw))
        except ValueError:
            return None

    async def screenshot(
        self, *, full_page: bool = False, quality: int = 60, timeout_sec: float = 40.0
    ) -> bytes:
        import base64

        # Kept under BROWSER_SCREENSHOT_TIMEOUT_SEC's default outer
        # asyncio.wait_for wrapper (_browser_snapshot.py) so a slow-but-live
        # capture hits this inner timeout with a clear message rather than
        # being cut off by the outer wrapper first.
        params: dict[str, Any] = {'format': 'jpeg', 'quality': quality}
        if full_page:
            params['captureBeyondViewport'] = True
        result = await self.page_send(
            'Page.captureScreenshot', params, timeout_sec=timeout_sec
        )
        return base64.b64decode(result.get('data', ''))

    # ── interaction ──────────────────────────────────────────────────

    async def click_index(self, index: int) -> str:
        box = await self.resolve_index(index)
        if box is None:
            raise RuntimeError(f'No element at index {index}; take a new snapshot.')
        for event_type in ('mousePressed', 'mouseReleased'):
            await self.page_send(
                'Input.dispatchMouseEvent',
                {
                    'type': event_type,
                    'x': box['x'],
                    'y': box['y'],
                    'button': 'left',
                    'clickCount': 1,
                },
            )
        await asyncio.sleep(0.2)
        return str(box.get('tag', ''))

    async def type_index(self, index: int, text: str, *, clear: bool = True) -> None:
        box = await self.resolve_index(index)
        if box is None:
            raise RuntimeError(f'No element at index {index}; take a new snapshot.')
        focused = await self.evaluate(
            f'(() => {{ const e = (window.__grinta_els||[])[{index}];'
            f' if (!e) return false; e.focus();'
            f' if ({json.dumps(bool(clear))}) {{'
            f'   if ("value" in e) e.value = ""; else e.textContent = ""; }}'
            f' return true; }})()'
        )
        if not focused:
            raise RuntimeError(f'No element at index {index}; take a new snapshot.')
        if text:
            await self.page_send('Input.insertText', {'text': text})

    async def scroll(self, *, delta_y: int = 0, delta_x: int = 0) -> None:
        await self.page_send(
            'Input.dispatchMouseEvent',
            {
                'type': 'mouseWheel',
                'x': 10,
                'y': 10,
                'deltaX': delta_x,
                'deltaY': delta_y,
            },
        )
        await asyncio.sleep(0.1)

    async def scroll_to_text(self, text: str) -> bool:
        found = await self.evaluate(
            f'(() => {{ const needle = {json.dumps(text)}.toLowerCase();'
            ' const walker = document.createTreeWalker(document.body,'
            ' NodeFilter.SHOW_TEXT);'
            ' while (walker.nextNode()) {'
            '   const n = walker.currentNode;'
            '   if ((n.textContent||"").toLowerCase().includes(needle)) {'
            '     const el = n.parentElement;'
            '     if (el) { el.scrollIntoView({block: "center"}); return true; } } }'
            ' return false; })()'
        )
        return bool(found)

    async def send_keys(self, keys: str) -> None:
        """Send a key chord such as ``Enter``, ``Tab`` or ``Control+a``."""
        parts = [part.strip() for part in keys.split('+') if part.strip()]
        if not parts:
            return
        modifier_bits = {'alt': 1, 'control': 2, 'ctrl': 2, 'meta': 4, 'shift': 8}
        modifiers = 0
        for part in parts[:-1]:
            modifiers |= modifier_bits.get(part.lower(), 0)
        key = parts[-1]
        named = {
            'enter': ('Enter', 13),
            'tab': ('Tab', 9),
            'escape': ('Escape', 27),
            'esc': ('Escape', 27),
            'backspace': ('Backspace', 8),
            'delete': ('Delete', 46),
            'arrowup': ('ArrowUp', 38),
            'arrowdown': ('ArrowDown', 40),
            'arrowleft': ('ArrowLeft', 37),
            'arrowright': ('ArrowRight', 39),
            'pageup': ('PageUp', 33),
            'pagedown': ('PageDown', 34),
            'home': ('Home', 36),
            'end': ('End', 35),
        }
        key_name, key_code = named.get(key.lower(), (key, ord(key[0]) if key else 0))
        for event_type in ('keyDown', 'keyUp'):
            params: dict[str, Any] = {
                'type': event_type,
                'key': key_name,
                'windowsVirtualKeyCode': key_code,
                'nativeVirtualKeyCode': key_code,
                'modifiers': modifiers,
            }
            if event_type == 'keyDown' and len(key_name) == 1 and not modifiers:
                params['text'] = key_name
            await self.page_send('Input.dispatchKeyEvent', params)

    async def select_option(self, index: int, value: str) -> str:
        """Select an option on a ``<select>`` by value, label or index."""
        result = await self.evaluate(
            f'(() => {{ const el = (window.__grinta_els||[])[{index}];'
            ' if (!el || el.tagName !== "SELECT") return "ERR:not-a-select";'
            f' const want = {json.dumps(value)};'
            ' let match = Array.from(el.options).find('
            '   o => o.value === want || o.text.trim() === want);'
            ' if (!match && /^\\d+$/.test(want)) match = el.options[Number(want)];'
            ' if (!match) return "ERR:no-option";'
            ' el.value = match.value;'
            ' el.dispatchEvent(new Event("input", {bubbles: true}));'
            ' el.dispatchEvent(new Event("change", {bubbles: true}));'
            ' return match.text.trim(); })()'
        )
        text = str(result or '')
        if text.startswith('ERR:'):
            reason = {
                'ERR:not-a-select': f'Element {index} is not a dropdown.',
                'ERR:no-option': f'No option matching {value!r}.',
            }.get(text, text)
            raise RuntimeError(reason)
        return text

    async def upload_file(self, index: int, path: str) -> None:
        """Set files on a file input identified by snapshot index."""
        document = await self.page_send(
            'DOM.getDocument', {'depth': -1, 'pierce': True}
        )
        root_id = document['root']['nodeId']
        # Give the element a marker attribute so CDP can find the same node.
        marked = await self.evaluate(
            f'(() => {{ const el = (window.__grinta_els||[])[{index}];'
            ' if (!el) return false;'
            ' el.setAttribute("data-grinta-upload", "1"); return true; })()'
        )
        if not marked:
            raise RuntimeError(f'No element at index {index}; take a new snapshot.')
        try:
            found = await self.page_send(
                'DOM.querySelector',
                {'nodeId': root_id, 'selector': '[data-grinta-upload="1"]'},
            )
            node_id = found.get('nodeId')
            if not node_id:
                raise RuntimeError(f'Could not resolve element {index} for upload.')
            await self.page_send(
                'DOM.setFileInputFiles', {'nodeId': node_id, 'files': [path]}
            )
        finally:
            await self.evaluate(
                '(() => { const e = document.querySelector('
                '"[data-grinta-upload=\\"1\\"]");'
                ' if (e) e.removeAttribute("data-grinta-upload"); })()'
            )


__all__ = [
    'CDPBrowser',
    'CDPConnection',
    'CDPError',
    'find_browser_binary',
]
