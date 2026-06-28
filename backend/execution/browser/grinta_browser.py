"""Native browser operations using browser-use (BrowserSession) — no nested Agent.

This module is a thin shim that exposes the public
``GrintaNativeBrowser`` class and its ``execute`` dispatcher. The
method bodies live in sibling modules; this file contains
one-line-forwarder class methods so monkey-patching of the methods
in tests (``self.editor._method = ...``) keeps working.

Per-mode helpers:
  - backend.execution.browser._browser_shared         (constants, trace, finalize, snapshot text)
  - backend.execution.browser._browser_cdp            (CDP low-level: resolve, preflight, capture, navigate)
  - backend.execution.browser._browser_snapshot       (snapshot + screenshot command bodies)
  - backend.execution.browser._browser_navigation     (start/close/navigate/go_back/tab command bodies)
  - backend.execution.browser._browser_interaction    (click/type/scroll/wait/extract/upload/select)

Pure code motion: no logic changes.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from backend.core.constants import BROWSER_SESSION_START_TIMEOUT_SEC
from backend.core.logging.logger import app_logger as logger
from backend.execution.browser._browser_cdp import (
    _navigate_direct_cdp,
)
from backend.execution.browser._browser_interaction import (
    dispatch_bus_event_impl as _dispatch_bus_event_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_click_impl as _execute_click_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_extract_impl as _execute_extract_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_scroll_impl as _execute_scroll_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_select_dropdown_impl as _execute_select_dropdown_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_send_keys_impl as _execute_send_keys_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_type_impl as _execute_type_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_upload_file_impl as _execute_upload_file_impl,
)
from backend.execution.browser._browser_interaction import (
    execute_wait_impl as _execute_wait_impl,
)
from backend.execution.browser._browser_interaction import (
    get_browser_node_impl as _get_browser_node_impl,
)
from backend.execution.browser._browser_interaction import (
    page_targets_ordered_impl as _page_targets_ordered_impl,
)
from backend.execution.browser._browser_interaction import (
    parse_browser_index_impl as _parse_browser_index_impl,
)
from backend.execution.browser._browser_interaction import (
    resolve_workspace_path_impl as _resolve_workspace_path_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_close_impl as _execute_close_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_close_tab_impl as _execute_close_tab_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_go_back_impl as _execute_go_back_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_list_tabs_impl as _execute_list_tabs_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_navigate_impl as _execute_navigate_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_start_impl as _execute_start_impl,
)
from backend.execution.browser._browser_navigation import (
    execute_switch_tab_impl as _execute_switch_tab_impl,
)
from backend.execution.browser._browser_navigation import (
    run_navigation_impl as _run_navigation_impl,
)
from backend.execution.browser._browser_shared import (
    StructuredExtractFn,
    _browser_trace,
    _finalize_observation,
)
from backend.execution.browser._browser_snapshot import (
    execute_screenshot_impl as _execute_screenshot_impl,
)
from backend.execution.browser._browser_snapshot import (
    execute_snapshot_impl as _execute_snapshot_impl,
)
from backend.execution.browser._browser_snapshot import (
    maybe_append_page_state_impl as _maybe_append_page_state_impl,
)
from backend.execution.browser._browser_snapshot import (
    snapshot_formatted_impl as _snapshot_formatted_impl,
)
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
)

__all__ = [
    'GrintaNativeBrowser',
    'StructuredExtractFn',
    # Re-exports for tests that import these as module-level functions.
    '_navigate_direct_cdp',
    '_finalize_observation',
]


class GrintaNativeBrowser:
    """Thin async wrapper around browser_use.Browser (BrowserSession)."""

    def __init__(
        self,
        downloads_dir: Path | str,
        *,
        workspace_root: Path | str | None = None,
    ) -> None:
        self._downloads = Path(downloads_dir)
        self._downloads.mkdir(parents=True, exist_ok=True)
        self._session: Any = None
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else self._downloads.resolve().parent
        )
        self._last_diff_lines: set[str] | None = None
        self._structured_extract: StructuredExtractFn | None = None

    def set_structured_extract(self, fn: StructuredExtractFn | None) -> None:
        """LLM-based JSON extract for ``browser extract`` (set by runtime bootstrap)."""
        self._structured_extract = fn

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            from browser_use import Browser as BrowserCls  # pyright: ignore[reportMissingImports]  # noqa: I001
        except ImportError as e:
            raise RuntimeError(
                'browser-use is not installed. Install the optional dependency group '
                '(`python scripts/bootstrap_env.py browser`) and run `uvx browser-use install` to '
                'download Chromium.'
            ) from e
        browser = BrowserCls(headless=True)
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

    async def _snapshot_formatted(self, browser: Any, mode: str) -> str:
        return await _snapshot_formatted_impl(self, browser, mode)

    async def _maybe_append_page_state(
        self,
        browser: Any,
        *,
        params: dict[str, Any],
        prefix: str,
    ) -> str:
        return await _maybe_append_page_state_impl(
            self, browser, params=params, prefix=prefix
        )

    async def _execute_start(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_start_impl(self, cmd, params)

    async def _execute_close(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_close_impl(self, cmd, params)

    async def _run_navigation(
        self,
        browser: Any,
        *,
        url: str,
        new_tab: bool,
        nav_budget: float,
    ) -> None:
        await _run_navigation_impl(
            self, browser, url=url, new_tab=new_tab, nav_budget=nav_budget
        )

    async def _execute_navigate(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_navigate_impl(self, cmd, params)

    async def _execute_snapshot(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_snapshot_impl(self, cmd, params)

    async def _execute_screenshot(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        return await _execute_screenshot_impl(self, cmd, params)

    @staticmethod
    def _parse_browser_index(
        cmd: str, value: Any, *, action_name: str
    ) -> tuple[int | None, Observation | None]:
        return _parse_browser_index_impl(cmd, value, action_name=action_name)

    async def _get_browser_node(
        self, browser: Any, *, cmd: str, index: int
    ) -> tuple[Any | None, Observation | None]:
        return await _get_browser_node_impl(self, browser, cmd=cmd, index=index)

    async def _execute_click(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_click_impl(self, cmd, params)

    async def _execute_type(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_type_impl(self, cmd, params)

    def _resolve_workspace_path(self, raw: str) -> tuple[Path | None, str | None]:
        return _resolve_workspace_path_impl(self, raw)

    @staticmethod
    def _page_targets_ordered(browser: Any) -> list[Any]:
        return _page_targets_ordered_impl(browser)

    async def _dispatch_bus_event(self, browser: Any, event_obj: Any) -> None:
        await _dispatch_bus_event_impl(self, browser, event_obj)

    async def _execute_scroll(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_scroll_impl(self, cmd, params)

    async def _execute_send_keys(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_send_keys_impl(self, cmd, params)

    async def _execute_wait(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_wait_impl(self, cmd, params)

    async def _execute_switch_tab(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        return await _execute_switch_tab_impl(self, cmd, params)

    async def _execute_close_tab(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_close_tab_impl(self, cmd, params)

    async def _execute_list_tabs(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_list_tabs_impl(self, cmd, params)

    async def _execute_go_back(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_go_back_impl(self, cmd, params)

    async def _execute_extract(self, cmd: str, params: dict[str, Any]) -> Observation:
        return await _execute_extract_impl(self, cmd, params)

    async def _execute_upload_file(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        return await _execute_upload_file_impl(self, cmd, params)

    async def _execute_select_dropdown(
        self, cmd: str, params: dict[str, Any]
    ) -> Observation:
        return await _execute_select_dropdown_impl(self, cmd, params)

    @staticmethod
    def _unknown_browser_command(cmd: str) -> Observation:
        return _finalize_observation(
            cmd,
            ErrorObservation(
                content=f'ERROR: Unknown browser command {cmd!r}. '
                'Use: start, close, navigate, snapshot, screenshot, click, type, '
                'scroll, send_keys, wait, switch_tab, close_tab, list_tabs, go_back, '
                'extract, upload_file, select_dropdown_option.'
            ),
        )

    async def execute(self, command: str, params: dict[str, Any]) -> Observation:
        cmd = (command or '').strip().lower()
        try:
            handlers = {
                'start': self._execute_start,
                'close': self._execute_close,
                'navigate': self._execute_navigate,
                'snapshot': self._execute_snapshot,
                'screenshot': self._execute_screenshot,
                'click': self._execute_click,
                'type': self._execute_type,
                'scroll': self._execute_scroll,
                'send_keys': self._execute_send_keys,
                'wait': self._execute_wait,
                'switch_tab': self._execute_switch_tab,
                'close_tab': self._execute_close_tab,
                'list_tabs': self._execute_list_tabs,
                'go_back': self._execute_go_back,
                'extract': self._execute_extract,
                'upload_file': self._execute_upload_file,
                'select_dropdown_option': self._execute_select_dropdown,
            }
            handler = handlers.get(cmd)
            if handler is None:
                return self._unknown_browser_command(cmd)
            return await handler(cmd, params)
        except RuntimeError as e:
            return _finalize_observation(cmd, ErrorObservation(content=f'ERROR: {e}'))
        except Exception as e:
            # WARNING is below the CLI's effective ERROR level and would be dropped.
            logger.error('browser tool failed: %s', e, exc_info=True)
            _browser_trace(f'exception: {type(e).__name__}: {e}')
            msg = str(e).strip() or type(e).__name__
            hint = ''
            if (
                'chromium' in msg.lower()
                or 'browser' in msg.lower()
                and 'executable' in msg.lower()
            ):
                hint = ' If the browser binary is missing, run: uvx browser-use install'
            return _finalize_observation(
                cmd,
                ErrorObservation(
                    content=f'ERROR: Browser operation failed: {msg}.{hint}'
                ),
            )
