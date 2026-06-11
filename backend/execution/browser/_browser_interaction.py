"""Interactive method bodies for GrintaNativeBrowser.

Module functions are extracted method bodies for the click, type,
scroll, send_keys, wait, extract, upload_file, and select_dropdown
commands on ``GrintaNativeBrowser``, plus the small helpers they
share (parse_browser_index, get_browser_node, resolve_workspace_path,
page_targets_ordered, dispatch_bus_event).

Module functions invoke other methods via ``self._method(...)`` so
monkey-patching of the class methods in tests still works.

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public class and ``execute`` dispatcher.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from backend.core.constants import (
    BROWSER_EXTRACT_TIMEOUT_SEC,
    BROWSER_WAIT_TIMEOUT_SEC,
)
from backend.execution.browser._browser_shared import (
    _MAX_TYPE_LEN,
    _finalize_observation,
    _snapshot_text_chain,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)


@staticmethod
def parse_browser_index_impl(
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


async def get_browser_node_impl(
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


async def execute_click_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content,
            command='browser click',
            exit_code=0,
        ),
    )


async def execute_type_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
    base = f'Typed into element index {index}.'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content,
            command='browser type',
            exit_code=0,
        ),
    )


async def execute_scroll_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
    direction = str(params.get('direction') or 'down').strip().lower()
    browser = await self._ensure_session()
    to_text = params.get('to_text')
    if to_text:
        return await self._scroll_to_text(cmd, browser, params, to_text)
    if direction in ('top', 'bottom'):
        return await self._scroll_to_edge(browser, params, direction)
    return await self._scroll_directional(cmd, browser, params, direction)


async def _scroll_to_text(
    self, cmd: str, browser: Any, params: dict[str, Any], to_text: Any
) -> Observation:
    from browser_use.browser.events import ScrollToTextEvent

    text = str(to_text).strip()
    if not text:
        return _finalize_observation(
            cmd, ErrorObservation(content='ERROR: to_text is empty.')
        )
    await self._dispatch_bus_event(
        browser, ScrollToTextEvent(text=text, direction='down')
    )
    base = 'Scrolled toward text match.'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser scroll', exit_code=0),
    )


async def _scroll_to_edge(
    self, browser: Any, params: dict[str, Any], direction: str
) -> Observation:
    from browser_use.browser.events import ScrollEvent

    amt = 50_000
    dir1 = 'up' if direction == 'top' else 'down'
    await self._dispatch_bus_event(
        browser, ScrollEvent(direction=dir1, amount=amt, node=None)
    )
    base = f'Scrolled {direction}.'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser scroll', exit_code=0),
    )


async def _scroll_directional(
    self, cmd: str, browser: Any, params: dict[str, Any], direction: str
) -> Observation:
    from browser_use.browser.events import ScrollEvent

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
        node, err2 = await self._get_browser_node(browser, cmd=cmd, index=six or 0)
        if err2 is not None:
            return err2
    await self._dispatch_bus_event(
        browser,
        ScrollEvent(direction=direction, amount=amount, node=node),
    )
    base = f'Scrolled {direction} by {amount}px.'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser scroll', exit_code=0),
    )


async def execute_send_keys_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
    from browser_use.browser.events import SendKeysEvent

    keys = str(params.get('keys') or '').strip()
    if not keys:
        return _finalize_observation(
            cmd, ErrorObservation(content='ERROR: keys required.')
        )
    browser = await self._ensure_session()
    await self._dispatch_bus_event(browser, SendKeysEvent(keys=keys))
    base = f'Sent keys: {keys!r}'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser send_keys', exit_code=0),
    )


async def _wait_for_timeout(
    browser: Any, params: dict[str, Any], timeout_sec: float
) -> str:
    from browser_use.browser.events import WaitEvent

    sec = min(float(params.get('seconds') or timeout_sec), 10.0)
    await browser.event_bus.dispatch(WaitEvent(seconds=sec))
    return f'Waited {sec}s.'


async def _wait_for_text(
    browser: Any, params: dict[str, Any], timeout_sec: float, cmd: str
) -> tuple[str | None, Observation | None]:
    needle = str(params.get('value') or '').strip()
    if not needle:
        return None, _finalize_observation(
            cmd,
            ErrorObservation(content='ERROR: value required for text wait.'),
        )
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        txt = await _snapshot_text_chain(browser)
        if needle in txt:
            return 'Text appeared.', None
        await asyncio.sleep(0.4)
    return None, _finalize_observation(
        cmd,
        ErrorObservation(
            content=f'ERROR: Timeout waiting for text after {timeout_sec:.0f}s.'
        ),
    )


async def _wait_for_selector(
    browser: Any, params: dict[str, Any], timeout_sec: float, cmd: str
) -> tuple[str | None, Observation | None]:
    needle = str(params.get('value') or '').strip()
    if not needle:
        return None, _finalize_observation(
            cmd,
            ErrorObservation(content='ERROR: value required for selector wait.'),
        )
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        txt = await _snapshot_text_chain(browser)
        if needle in txt:
            return 'Selector/text appeared in DOM dump.', None
        await asyncio.sleep(0.4)
    return None, _finalize_observation(
        cmd,
        ErrorObservation(
            content=f'ERROR: Timeout waiting for selector substring after {timeout_sec:.0f}s.'
        ),
    )


async def _wait_for_network_idle(
    browser: Any, timeout_sec: float, cmd: str
) -> tuple[str | None, Observation | None]:
    prev: str | None = None
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        cur = await _snapshot_text_chain(browser)
        if prev is not None and cur == prev:
            return 'DOM stable (network_idle heuristic).', None
        prev = cur
        await asyncio.sleep(0.5)
    return None, _finalize_observation(
        cmd,
        ErrorObservation(
            content=f'ERROR: Timeout waiting for stable DOM after {timeout_sec:.0f}s.'
        ),
    )


async def execute_wait_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
    wait_kind = (
        str(params.get('wait_kind') or params.get('wait_for') or 'timeout')
        .strip()
        .lower()
    )
    timeout_sec = min(
        float(params.get('timeout_sec') or 10.0), BROWSER_WAIT_TIMEOUT_SEC
    )
    browser = await self._ensure_session()

    base, err = await self._dispatch_wait(browser, params, wait_kind, timeout_sec, cmd)
    if err is not None:
        return err

    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser wait', exit_code=0),
    )


async def _dispatch_wait(
    self,
    browser: Any,
    params: dict[str, Any],
    wait_kind: str,
    timeout_sec: float,
    cmd: str,
) -> tuple[str, Observation | None]:
    if wait_kind == 'timeout':
        return await _wait_for_timeout(browser, params, timeout_sec), None
    if wait_kind == 'text':
        return await _wait_for_text(browser, params, timeout_sec, cmd)
    if wait_kind in ('selector', 'css'):
        return await _wait_for_selector(browser, params, timeout_sec, cmd)
    if wait_kind == 'network_idle':
        return await _wait_for_network_idle(browser, timeout_sec, cmd)
    return '', _finalize_observation(
        cmd,
        ErrorObservation(content=f'ERROR: unknown wait_kind {wait_kind!r}.'),
    )


async def execute_extract_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
    if self._structured_extract is None:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=('ERROR: Structured extract is not configured on this runtime.')
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
        CmdOutputObservation(content=out, command='browser extract', exit_code=0),
    )


async def execute_upload_file_impl(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
    from browser_use.browser.events import UploadFileEvent

    raw_path = str(params.get('path') or '').strip()
    resolved, perr = self._resolve_workspace_path(raw_path)
    if perr:
        return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {perr}'))
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content, command='browser upload_file', exit_code=0
        ),
    )


async def execute_select_dropdown_impl(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
    from browser_use.browser.events import SelectDropdownOptionEvent

    opt_text = params.get('option_text')
    opt_val = params.get('option_value')
    choice = (str(opt_text).strip() if opt_text else '') or (
        str(opt_val).strip() if opt_val else ''
    )
    if not choice:
        return _finalize_observation(
            cmd,
            ErrorObservation(content='ERROR: option_text or option_value required.'),
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content,
            command='browser select_dropdown_option',
            exit_code=0,
        ),
    )


def resolve_workspace_path_impl(self, raw: str) -> tuple[Path | None, str | None]:
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
def page_targets_ordered_impl(browser: Any) -> list[Any]:
    try:
        pages = browser.get_page_targets()
    except Exception:
        pages = []
    return list(pages or [])


async def dispatch_bus_event_impl(self, browser: Any, event_obj: Any) -> None:
    evt = browser.event_bus.dispatch(event_obj)
    await evt
    await evt.event_result(raise_if_any=True, raise_if_none=False)
