from __future__ import annotations

import asyncio
import contextlib
import shlex
import time
from typing import Any

from textual.widgets import (
    ListView,
    TextArea,
)

from backend.cli.tui._app_constants import _tui_logger
from backend.cli.tui._app_dialogs import GrintaSessionsDialog, GrintaSettingsDialog
from backend.cli.tui._app_helpers import (
    _strip_ansi,
    _strip_terminal_control_literals,
)
from backend.cli.tui._app_small_widgets import (
    InputBar,
)
from backend.core.logger import app_logger as logger
from backend.ledger import EventStreamSubscriber


def _parse_sessions_tui_args(args: list[str]) -> dict[str, Any]:
    remaining = list(args)
    if remaining and remaining[0].lower() == 'list':
        remaining.pop(0)

    result: dict[str, Any] = {
        'search': None,
        'sort_by': 'updated',
        'limit': 20,
        'preview_idx': None,
        'delete_targets': [],
        'error': None,
    }

    i = 0
    while i < len(remaining):
        i, done = _parse_one_sessions_arg(remaining, i, result)
        if done:
            break

    return result


def _parse_one_sessions_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool]:
    remaining[i]
    handlers = [
        _try_parse_search_arg,
        _try_parse_sort_arg,
        _try_parse_delete_arg,
        _try_parse_limit_arg,
        _try_parse_preview_arg,
    ]
    for handler in handlers:
        new_i, handled, error = handler(remaining, i, result)
        if error:
            result['error'] = error
            return i, True
        if handled:
            return new_i, False

    return _parse_positional_limit_arg(remaining, i, result)


def _try_parse_search_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool, str | None]:
    if remaining[i] in ('--search', '-s') and i + 1 < len(remaining):
        result['search'] = remaining[i + 1]
        return i + 2, True, None
    return i, False, None


def _try_parse_sort_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool, str | None]:
    if remaining[i] == '--sort' and i + 1 < len(remaining):
        allowed = ('updated', 'created', 'events', 'cost', 'model')
        if remaining[i + 1] not in allowed:
            return i, False, f'Sort must be one of: {", ".join(allowed)}'
        result['sort_by'] = remaining[i + 1]
        return i + 2, True, None
    return i, False, None


def _try_parse_delete_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool, str | None]:
    if remaining[i] in ('--delete', '-d') and i + 1 < len(remaining):
        i += 1
        while i < len(remaining) and not remaining[i].startswith('-'):
            result['delete_targets'].append(remaining[i])
            i += 1
        return i, True, None
    return i, False, None


def _try_parse_limit_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool, str | None]:
    if remaining[i] in ('--limit', '-l') and i + 1 < len(remaining):
        try:
            result['limit'] = int(remaining[i + 1])
        except ValueError:
            return i, False, 'Limit must be a number.'
        if result['limit'] < 1:
            return i, False, 'Limit must be 1 or greater.'
        return i + 2, True, None
    return i, False, None


def _try_parse_preview_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool, str | None]:
    if remaining[i] == '--preview' and i + 1 < len(remaining):
        result['preview_idx'] = remaining[i + 1]
        return i + 2, True, None
    return i, False, None


def _parse_positional_limit_arg(
    remaining: list[str], i: int, result: dict[str, Any]
) -> tuple[int, bool]:
    token = remaining[i]
    try:
        parsed_limit = int(token)
    except ValueError:
        result['error'] = f'Unknown option: {token}'
        return i, True
    if parsed_limit < 1:
        result['error'] = 'Limit must be 1 or greater.'
        return i, True
    result['limit'] = parsed_limit
    return i + 1, False


class _AppScreenInputMixin:
    """Input-related methods of GrintaScreen."""

    def action_history_prev(self) -> None:
        """Navigate backward through command history."""
        if not self._command_history:
            return
        ta = self.query_one('#input', TextArea)
        if self._history_index == -1:
            self._history_index = len(self._command_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        ta.text = self._command_history[self._history_index]
        ta.cursor = (len(ta.text.splitlines()), 0)

    def action_history_next(self) -> None:
        """Navigate forward through command history."""
        ta = self.query_one('#input', TextArea)
        if self._history_index == -1:
            return
        self._history_index -= 1
        if self._history_index < 0:
            self._history_index = -1
            ta.text = ''
        else:
            ta.text = self._command_history[self._history_index]
        ta.cursor = (len(ta.text.splitlines()), 0)

    def _resize_input_bar(self) -> None:
        try:
            ta = self.query_one('#input', TextArea)
            bar = self.query_one('#input-bar', InputBar)
        except Exception:
            return
        line_count = ta.text.count('\n') + 1
        max_total = max(
            self._MIN_INPUT_HEIGHT,
            int(self.size.height * self._INPUT_HEIGHT_FRACTION),
        )
        non_content = 3
        max_content = max_total - non_content
        content_rows = min(max(line_count, 2), max_content)
        bar.styles.height = non_content + content_rows

    _COMMAND_FLAGS: dict[str, list[str]] = {
        '/sessions': ['--limit', '--search', '--sort', '--preview', '--delete'],
        '/help': ['--all', '--search'],
    }

    def _accept_suggestion(self, ta: Any, lst: Any) -> None:
        selected = lst.index if lst.index is not None else 0
        if 0 <= selected < len(self._suggestion_matches):
            ta.text = self._suggestion_matches[selected] + ' '
        lst.add_class('-hidden')
        self._suggestion_matches = []
        ta.focus()

    def _complete_command_name(self, ta: Any, cmd: str) -> None:
        matches = [name for name in self._SLASH_HINTS if name.startswith(cmd)]
        if len(matches) == 1:
            ta.text = matches[0] + ' '

    def _complete_command_flag(
        self, ta: Any, cmd: str, parts: list[str], raw: str
    ) -> None:
        flags = self._COMMAND_FLAGS.get(cmd)
        if not flags or not parts[-1].startswith('--'):
            return
        matches = [flag for flag in flags if flag.startswith(parts[-1])]
        if len(matches) == 1:
            prefix = raw.rstrip()
            ta.text = prefix[: -len(parts[-1])] + matches[0] + ' '

    def action_complete_command(self) -> None:
        ta = self.query_one('#input', TextArea)
        raw = _strip_ansi(ta.text)
        if not raw.strip().startswith('/'):
            return

        lst = self.query_one('#suggestions-list', ListView)
        if not lst.has_class('-hidden') and self._suggestion_matches:
            self._accept_suggestion(ta, lst)
            return

        try:
            parts = shlex.split(raw.strip())
        except ValueError:
            self.add_error('Cannot autocomplete: malformed command.')
            return
        if not parts:
            return

        cmd = parts[0].lower()
        if len(parts) == 1:
            self._complete_command_name(ta, cmd)
            return

        self._complete_command_flag(ta, cmd, parts, raw)

    def _submit_handle_empty_text(self) -> None:
        if self._welcome_visible:
            _tui_logger.debug('action_submit_input: routing to welcome select')
            self.action_welcome_select()
        elif self._active_communicate_card is not None and getattr(
            self._active_communicate_card, 'has_options', False
        ):
            _tui_logger.debug('action_submit_input: routing to communicate selection')
            self._active_communicate_card.action_submit_option()
        else:
            _tui_logger.debug('action_submit_input: empty text, ignoring')

    def _submit_clear_ui_state(self) -> None:
        if self._welcome_visible:
            self._hide_welcome()
        if self._active_communicate_card is not None:
            try:
                self._active_communicate_card.set_active(False)
            except Exception:
                pass
            self._active_communicate_card = None

    def _submit_spawn_input_task(self, text: str) -> None:
        try:
            task = asyncio.create_task(self._handle_input(text))
            _tui_logger.debug(f'action_submit_input: task created {task}')

            def _on_done(t: asyncio.Task[Any]) -> None:
                exc = t.exception()
                if exc:
                    _tui_logger.debug(
                        f'_handle_input task FAILED: {type(exc).__name__}: {exc}'
                    )
                else:
                    _tui_logger.debug('_handle_input task completed OK')

            task.add_done_callback(_on_done)
        except Exception as exc:
            _tui_logger.debug(
                f'action_submit_input: create_task FAILED: {type(exc).__name__}: {exc}'
            )

    def action_submit_input(self) -> None:
        _tui_logger.debug(
            f'action_submit_input: lock_locked={self._input_lock.locked()}'
        )
        if getattr(self, '_turn_in_flight', False):
            _tui_logger.debug('action_submit_input: turn in flight, ignoring')
            return
        if self._input_lock.locked():
            _tui_logger.debug('action_submit_input: lock held, ignoring')
            return
        ta = self.query_one('#input', TextArea)
        clean_text = _strip_terminal_control_literals(ta.text)
        if clean_text != ta.text:
            ta.text = clean_text
        text = _strip_ansi(clean_text).strip()
        _tui_logger.debug(f'action_submit_input: text_len={len(text)}')
        if not text:
            self._submit_handle_empty_text()
            return
        self._submit_clear_ui_state()
        if not self._command_history or self._command_history[-1] != text:
            self._command_history.append(text)
        self._history_index = -1
        _tui_logger.debug('action_submit_input: creating task for _handle_input')
        self._submit_spawn_input_task(text)

    async def _ensure_controller_ready(self) -> None:
        """Ensure controller is initialized, bootstrapping if needed."""
        if self._bootstrapping is not None and not self._bootstrapping.is_set():
            _tui_logger.debug('_handle_input: waiting for background bootstrap')
            logger.info('[TUI] _handle_input: waiting for background bootstrap')
            await self._bootstrapping.wait()

        if self._controller is not None:
            _tui_logger.debug(
                '_handle_input: controller exists, dispatch will ensure task'
            )
            logger.info('[TUI] _handle_input: controller exists')
            return

        if self._controller is None:
            _tui_logger.debug('_handle_input: calling _bootstrap()')
            logger.info('[TUI] _handle_input: bootstrapping (no controller)')
            await self._bootstrap()

        if self._controller is None:
            raise RuntimeError('Bootstrap failed to initialize controller')

        _tui_logger.debug(
            f'_handle_input: _bootstrap done, state={self._controller.get_agent_state()}'
        )
        logger.info(
            '[TUI] _handle_input: bootstrap complete, state=%s',
            self._controller.get_agent_state(),
        )

    def _handle_input_error(self, exc: Exception) -> None:
        """Handle errors during input processing."""
        _tui_logger.debug(f'_handle_input: EXCEPTION in setup: {exc}')
        logger.exception('[TUI] _handle_input setup FAILED')
        self.add_error(f'Agent error: {type(exc).__name__}: {exc}')
        self._render_hud_bar()
        if self._controller:
            try:
                actual = str(self._controller.get_agent_state())
                self._hud.update_agent_state(actual or 'Error')
            except Exception:
                self._hud.update_agent_state('Error')
        self.query_one('#input-bar', InputBar).remove_class('processing')
        self._render_hud_bar()

    async def _handle_input_prepare_ui(self) -> None:
        if self._renderer:
            await self._renderer.drain_events_async()
        ta = self.query_one('#input', TextArea)
        ta.clear()
        lst = self.query_one('#suggestions-list', ListView)
        lst.add_class('-hidden')
        self._suggestion_matches = []
        ta.focus()
        self._scroll_to_bottom()

    async def _handle_input_dispatch(self, agent_text: str) -> None:
        try:
            _tui_logger.debug('_handle_input: calling _dispatch_to_agent()')
            logger.info('[TUI] _handle_input: dispatching to agent')
            await self._dispatch_to_agent(agent_text)
            _tui_logger.debug(
                f'_handle_input: _dispatch_to_agent done, state={self._controller.get_agent_state()}'
            )
            logger.info(
                '[TUI] _handle_input: dispatch complete, state=%s',
                self._controller.get_agent_state() if self._controller else 'N/A',
            )
        except Exception as exc:
            _tui_logger.debug(f'_handle_input: EXCEPTION in dispatch: {exc}')
            logger.exception('[TUI] _handle_input FAILED')
            self.add_error(f'Agent error: {type(exc).__name__}: {exc}')
            self._render_hud_bar()
            if self._controller:
                try:
                    actual = str(self._controller.get_agent_state())
                    self._hud.update_agent_state(actual or 'Error')
                    self._render_hud_bar()
                except Exception:
                    self._hud.update_agent_state('Error')
                    self._render_hud_bar()
        finally:
            self.finalize_thinking()
            self._render_hud_bar()
            self.query_one('#input-bar', InputBar).remove_class('processing')
            if self._renderer:
                self._renderer.flush_live_ui(terminal=True)
                await self._renderer.drain_events_async()
            actual_state = (
                str(self._controller.get_agent_state()) if self._controller else ''
            )
            self._hud.update_agent_state(actual_state or 'Ready')
            self._render_hud_bar()
            self._turn_in_flight = False

    async def _handle_input(self, text: str) -> None:
        try:
            _tui_logger.debug(f'_handle_input ENTER text={text[:80]}')
        except Exception as exc:
            _tui_logger.debug(
                f'_handle_input: _trace FAILED: {type(exc).__name__}: {exc}'
            )

        agent_text: str | None = None
        async with self._input_lock:
            await self._handle_input_prepare_ui()

            if text.startswith('/'):
                await self._handle_slash_command(text)
                return

            if self._turn_in_flight:
                _tui_logger.debug('_handle_input: turn already in flight, ignoring')
                return

            self.add_user_message(text)
            self._render_hud_bar()
            self.query_one('#input-bar', InputBar).add_class('processing')

            try:
                _tui_logger.debug(
                    f'_handle_input: controller={self._controller is not None}'
                )
                await self._ensure_controller_ready()
                assert self._controller is not None, (
                    'Controller must be initialized after agent task setup'
                )
                if getattr(self, '_pending_llm_config_apply', False):
                    self._apply_llm_config_to_active_session(self._config)
                agent_text = text
                self._turn_in_flight = True
            except Exception as exc:
                self._handle_input_error(exc)
                return

        if agent_text is None:
            return

        await self._handle_input_dispatch(agent_text)

    async def _handle_slash_command(self, text: str) -> None:
        raw = text.strip()
        if not raw:
            return
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            self.add_error(f'Invalid command syntax: {exc}')
            return
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd in ('/help', '/h', '/?'):
            self.show_help()
        elif cmd in ('/clear', '/c'):
            self.clear_transcript()
        elif cmd in ('/quit', '/q', '/exit'):
            self._agent_running = False
            self.app.exit()
        elif cmd == '/settings':
            self.run_worker(self._open_settings_tui(), exclusive=True)
        elif cmd == '/sessions':
            self.run_worker(self._run_sessions_tui(args), exclusive=True)
        elif cmd == '/resume':
            self.run_worker(self._run_resume_tui(args), exclusive=True)
        else:
            self.add_error(f'Unknown command: {text}')

    async def _open_settings_tui(self) -> None:
        from backend.cli.config_manager import (
            get_current_model,
            update_api_key,
            update_model,
        )
        from backend.core.config import load_app_config

        self._config = load_app_config(set_logging_levels=False)
        try:
            result = await self.app.push_screen_wait(GrintaSettingsDialog(self._config))
        except Exception as exc:
            logger.exception('[TUI] /settings dialog failed')
            self.add_error(f'/settings failed: {type(exc).__name__}: {exc}')
            return
        if not result:
            return
        try:
            provider = str(result.get('provider', '')).strip()
            update_model(
                str(result.get('model', '')).strip(),
                provider=provider or None,
                reasoning_effort=str(result.get('reasoning_effort', '')).strip()
                or None,
                clear_base_url=True,
            )
            api_key = str(result.get('api_key', '')).strip()
            if api_key:
                update_api_key(api_key, provider=provider or None)
        except Exception as exc:
            logger.exception('[TUI] /settings failed to persist')
            self.add_error(f'/settings failed: {type(exc).__name__}: {exc}')
            return

        self._config = load_app_config()
        runtime_status = self._apply_llm_config_to_active_session(self._config)
        self._hud.update_model(get_current_model(self._config))
        from backend.integrations.mcp.native_backends import count_user_visible_mcp_servers

        self._hud.update_mcp_servers(count_user_visible_mcp_servers(self._config))
        self._render_hud_bar()
        self.notify(
            f'Settings updated ({runtime_status})',
            severity='information',
            timeout=2.5,
        )

    async def _run_sessions_tui(self, args: list[str]) -> None:
        parsed = _parse_sessions_tui_args(args)
        if parsed['error'] is not None:
            self.add_error(parsed['error'])
            return

        sid_to_resume = await self.app.push_screen_wait(
            GrintaSessionsDialog(
                self._config,
                search=parsed['search'],
                sort_by=parsed['sort_by'],
                limit=parsed['limit'],
                preview_target=parsed['preview_idx'],
                delete_targets=parsed['delete_targets'],
            )
        )
        if sid_to_resume:
            await self._resume_session_target(sid_to_resume)

    async def _run_resume_tui(self, args: list[str]) -> None:
        if len(args) != 1:
            self.add_error('Usage: /resume <N|session_id>')
            return
        await self._resume_session_target(args[0])

    async def _resume_wait_and_bootstrap(self, resolved_id: str) -> None:
        if self._bootstrapping is not None and not self._bootstrapping.is_set():
            await self._bootstrapping.wait()
        await self._teardown_active_session()
        await self._bootstrap(session_id=resolved_id)
        if self._controller is None:
            raise RuntimeError('Resume bootstrap did not initialize controller.')

    async def _resume_session_target(self, target: str) -> None:
        from backend.cli.session_manager import resolve_session_id

        cleaned_target = (target or '').strip()
        if not cleaned_target:
            self.add_error('Usage: /resume <N|session_id>')
            return

        resolved_id, resolve_error = resolve_session_id(cleaned_target, self._config)
        if resolve_error or resolved_id is None:
            self.add_error(resolve_error or f'No session matches: {cleaned_target}')
            return

        self.add_system_message(f'Resuming session: {resolved_id}')
        self._phase_label = 'Loading…'
        self._phase_started_at = time.monotonic()
        self._render_hud_bar()
        input_bar = self.query_one('#input-bar', InputBar)
        input_bar.add_class('processing')
        try:
            await self._resume_wait_and_bootstrap(resolved_id)
        except Exception as exc:
            logger.exception('[TUI] /resume failed')
            self.add_error(f'Resume failed: {type(exc).__name__}: {exc}')
        else:
            self.add_success(
                f'Session {resolved_id[:12]} resumed. Send a message to continue.'
            )
        finally:
            input_bar.remove_class('processing')
            self.finalize_thinking()
            self._render_hud_bar()

    async def _cancel_old_agent_task(self) -> None:
        old_task = self._agent_task
        self._agent_task = None
        if old_task is not None and not old_task.done():
            old_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError, asyncio.TimeoutError, Exception
            ):
                await asyncio.wait_for(old_task, timeout=5.0)

    async def _stop_old_controller(self) -> None:
        old_controller = self._controller
        self._controller = None
        if old_controller is not None:
            mark_interrupt = getattr(old_controller, 'mark_user_interrupt_stop', None)
            if callable(mark_interrupt):
                with contextlib.suppress(Exception):
                    mark_interrupt()
            stop_fn = getattr(old_controller, 'stop', None)
            if callable(stop_fn):
                with contextlib.suppress(asyncio.TimeoutError, Exception):
                    await asyncio.wait_for(stop_fn(), timeout=5.0)

    async def _close_old_runtime(self) -> None:
        old_runtime = self._runtime_stub
        self._runtime_stub = None
        if old_runtime is not None:
            rebind = getattr(old_runtime, 'rebind_event_stream', None)
            if callable(rebind):
                with contextlib.suppress(Exception):
                    rebind(None)
            close_runtime = getattr(old_runtime, 'close', None)
            if callable(close_runtime):
                with contextlib.suppress(Exception):
                    close_runtime()

    async def _close_old_event_stream(self) -> None:
        old_stream = self._event_stream
        self._event_stream = None
        if old_stream is not None:
            with contextlib.suppress(Exception):
                old_stream.unsubscribe(EventStreamSubscriber.CLI, old_stream.sid)
            close_fn = getattr(old_stream, 'close', None)
            if callable(close_fn):
                with contextlib.suppress(Exception):
                    close_fn()
        self._memory_stub = None

    async def _teardown_active_session(self) -> None:
        await self._cancel_old_agent_task()
        await self._stop_old_controller()
        await self._close_old_runtime()
        await self._close_old_event_stream()
