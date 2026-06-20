"""Navigation/tab/history method bodies for GrintaNativeBrowser.

Module functions are extracted method bodies for the start, close,
navigate, go_back, switch_tab, close_tab, and list_tabs commands
on ``GrintaNativeBrowser``. They are called as one-line forwarders
from the class. Module functions invoke other methods via
``self._method(...)`` so monkey-patching of the class methods in
tests still works.

Extracted from ``backend.execution.browser.grinta_browser`` to keep
that module focused on the public class and ``execute`` dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from backend.core.constants import BROWSER_NAVIGATE_TOTAL_TIMEOUT_SEC
from backend.core.logging.logger import app_logger as logger
from backend.execution.browser._browser_cdp import _navigate_direct_cdp
from backend.execution.browser._browser_shared import (
    _await_nav_event,
    _browser_trace,
    _finalize_observation,
    _validate_http_url,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    Observation,
)


async def execute_start_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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


async def execute_close_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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


async def run_navigation_impl(
    self,
    browser: Any,
    *,
    url: str,
    new_tab: bool,
    nav_budget: float,
) -> None:
    if not new_tab:
        await asyncio.wait_for(_navigate_direct_cdp(browser, url), timeout=nav_budget)
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


async def execute_navigate_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content,
            command='browser navigate',
            exit_code=0,
        ),
    )


async def execute_go_back_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
    from browser_use.browser.events import GoBackEvent

    browser = await self._ensure_session()
    await self._dispatch_bus_event(browser, GoBackEvent())
    base = 'Navigated back in history.'
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser go_back', exit_code=0),
    )


async def execute_switch_tab_impl(
    self, cmd: str, params: dict[str, Any]
) -> Observation:
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(
            content=content, command='browser switch_tab', exit_code=0
        ),
    )


async def execute_close_tab_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
    content = await self._maybe_append_page_state(browser, params=params, prefix=base)
    return _finalize_observation(
        cmd,
        CmdOutputObservation(content=content, command='browser close_tab', exit_code=0),
    )


async def execute_list_tabs_impl(self, cmd: str, params: dict[str, Any]) -> Observation:
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
        CmdOutputObservation(content=body, command='browser list_tabs', exit_code=0),
    )
