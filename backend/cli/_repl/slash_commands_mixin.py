"""Slash-command and inspection mixin for :class:`backend.cli.repl.Repl`.

Holds the ``/checkpoint``, ``/autonomy`` and slash-command handlers so the
main REPL module can stay close to the project's per-file LOC budget.

The mixin assumes the host class provides:

* attributes: ``_renderer``, ``_console``, ``_config``, ``_hud``,
  ``_controller``, ``_event_stream``, ``_next_action``, ``_pending_resume``,
  ``_last_user_message``;
* helper methods: ``_warn``, ``_usage``, ``_reject_extra_args``,
  ``_command_project_root``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from backend.cli.config_manager import get_current_model
from backend.cli.hud import HUDBar
from backend.cli.settings_tui import open_settings
from backend.core.config import load_app_config
from backend.ledger.action import MessageAction


class SlashCommandsMixin:
    """Mixin providing the slash-command surface of the REPL."""

    # -- checkpoint inspection --------------------------------------------

    def _resolve_rollback_manager(self):
        """Return the active RollbackManager for the current session.

        The value is resolved via the controller's middleware, or ``None`` if
        checkpoints are not available in this session.
        """
        try:
            controller = getattr(self, '_controller', None) or getattr(
                self, '_orchestrator', None
            )
            if controller is None:
                return None
            mw = getattr(controller, '_rollback_middleware', None)
            if mw is None:
                return None
            return getattr(mw, '_manager', None)
        except Exception:
            return None

    def _handle_checkpoint_list(self, args: list[str]) -> None:
        """Render up to ``limit`` checkpoints (default 10, newest first)."""
        limit = self._parse_checkpoint_limit(args)
        if limit is None:
            return
        manager = self._resolve_rollback_manager()
        if manager is None:
            self._notify_no_rollback_manager(
                'No active rollback manager (workspace may not be initialised yet).'
            )
            return
        try:
            entries = manager.list_checkpoints()
        except Exception as exc:
            self._warn(f'Failed to list checkpoints: {exc}')
            return
        if not entries:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'No checkpoints recorded yet.', title='checkpoint'
                )
            return
        # Newest first.
        entries = sorted(entries, key=lambda e: e.get('timestamp', 0), reverse=True)[:limit]
        body = '\n'.join(self._format_checkpoint_entry(e) for e in entries)
        if self._renderer is not None:
            self._renderer.add_system_message(body, title='checkpoint list')

    def _parse_checkpoint_limit(self, args: list[str]) -> int | None:
        if not args:
            return 10
        try:
            return max(1, int(args[0]))
        except ValueError:
            self._warn('Usage: /checkpoint list [limit]')
            return None

    def _notify_no_rollback_manager(self, message: str) -> None:
        if self._renderer is not None:
            self._renderer.add_system_message(message, title='checkpoint')

    @staticmethod
    def _format_checkpoint_entry(e: dict[str, Any]) -> str:
        from datetime import datetime as _dt

        ts = e.get('timestamp', 0)
        try:
            ts_str = _dt.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_str = str(ts)
        return (
            f"  {e.get('id', '?')[:12]:<12} {ts_str}  "
            f"{e.get('checkpoint_type', '?'):<18} {e.get('description', '')[:60]}"
        )

    def _handle_checkpoint_diff(self, args: list[str]) -> None:
        """Show a git diff (or directory diff fallback) since a checkpoint."""
        if not args:
            self._warn('Usage: /checkpoint diff <id>')
            return
        cp_id = args[0]
        manager = self._resolve_rollback_manager()
        if manager is None:
            self._notify_no_rollback_manager('No active rollback manager.')
            return
        match = self._find_checkpoint_match(manager, cp_id)
        if match is None:
            return
        diff_text = self._compute_checkpoint_diff_text(
            match.get('git_commit_sha'), manager.workspace_path,
        )
        if self._renderer is not None:
            # Trim to keep the panel manageable.
            if len(diff_text) > 8000:
                diff_text = diff_text[:8000] + '\n[... diff truncated ...]\n'
            self._renderer.add_markdown_block(
                f"checkpoint diff {match.get('id', '?')[:12]}",
                f'```diff\n{diff_text}\n```',
            )

    def _find_checkpoint_match(
        self, manager: Any, cp_id: str,
    ) -> dict[str, Any] | None:
        try:
            entries = manager.list_checkpoints()
        except Exception as exc:
            self._warn(f'Failed to list checkpoints: {exc}')
            return None
        match = next(
            (e for e in entries if str(e.get('id', '')).startswith(cp_id)),
            None,
        )
        if match is None:
            self._warn(f'Checkpoint not found: {cp_id}')
        return match

    @staticmethod
    def _compute_checkpoint_diff_text(
        sha: Any, workspace_path: Any,
    ) -> str:
        if not sha:
            return (
                '(checkpoint has no git commit; file-snapshot diff is not implemented '
                'in the CLI — use checkpoint(revert) to roll back instead).'
            )
        import subprocess as _sp

        try:
            proc = _sp.run(
                ['git', 'diff', str(sha)],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return proc.stdout or proc.stderr or '(empty diff)'
        except Exception as exc:
            return f'(git diff failed: {exc})'

    # -- autonomy control --------------------------------------------------

    def _handle_autonomy_command(self, parsed) -> None:
        """View or change the autonomy level."""
        from backend.cli.repl import _AUTONOMY_LEVEL_HINTS

        valid_levels = tuple(_AUTONOMY_LEVEL_HINTS)

        if not parsed.args:
            self._show_current_autonomy(valid_levels)
            return

        if len(parsed.args) > 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return

        new_level = parsed.args[0].lower()
        if new_level not in valid_levels:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f"Invalid level '{new_level}'. Use: {', '.join(valid_levels)}",
                    title='warning',
                )
            return

        self._apply_autonomy_level(new_level)

    def _show_current_autonomy(self, valid_levels: tuple[str, ...]) -> None:
        from backend.cli.repl import _AUTONOMY_LEVEL_HINTS

        level = self._get_current_autonomy()
        if self._renderer is None:
            return
        level_lines = '\n'.join(
            f'  {name:<10} — {_AUTONOMY_LEVEL_HINTS[name]}'
            for name in valid_levels
        )
        self._renderer.add_system_message(
            f'Autonomy: {level}\n'
            f'{level_lines}\n'
            f'Change with: /autonomy <{"|".join(valid_levels)}>',
            title='autonomy',
        )

    def _apply_autonomy_level(self, new_level: str) -> None:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = new_level
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f'Autonomy set to: {new_level}', title='autonomy'
                    )
                return
        if self._renderer is not None:
            self._renderer.add_system_message(
                'No active controller. Send a message first to initialize, then set autonomy.',
                title='warning',
            )

    def _get_current_autonomy(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                return str(getattr(ac, 'autonomy_level', 'balanced'))
        return 'balanced (default)'

    # -- slash commands ----------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle a /command. Returns True to continue REPL, False to exit."""
        from backend.cli.repl import (
            SlashCommandParseError,
            _parse_slash_command,
        )

        try:
            parsed = _parse_slash_command(text)
        except SlashCommandParseError as exc:
            self._warn(str(exc))
            return True
        return self._handle_parsed_command(parsed)

    # Dispatch table for slash commands handled by ``_handle_parsed_command``.
    # Each method returns ``True`` to keep the REPL running, ``False`` to exit.
    # Methods that do not look at ``parsed`` may take ``parsed`` and ignore it.
    _COMMAND_DISPATCH: dict[str, str] = {
        '/exit': '_cmd_exit',
        '/quit': '_cmd_exit',
        '/settings': '_cmd_settings',
        '/clear': '_cmd_clear',
        '/status': '_cmd_status',
        '/cost': '_cmd_cost',
        '/diff': '_cmd_diff',
        '/think': '_cmd_think',
        '/checkpoint': '_cmd_checkpoint',
        '/copy': '_cmd_copy',
        '/sessions': '_cmd_sessions',
        '/resume': '_cmd_resume',
        '/autonomy': '_cmd_autonomy',
        '/help': '_cmd_help',
        '/model': '_cmd_model',
        '/compact': '_cmd_compact',
        '/retry': '_cmd_retry',
    }

    def _handle_parsed_command(self, parsed) -> bool:
        """Handle a parsed /command. Returns True to continue, False to exit."""
        method_name = self._COMMAND_DISPATCH.get(parsed.name)
        if method_name is not None:
            return getattr(self, method_name)(parsed)
        self._render_unknown_command(parsed.raw_name)
        return True

    def _render_unknown_command(self, raw_cmd: str) -> None:
        from backend.cli.repl import _closest_command_names

        if self._renderer is None:
            return
        suggestion_text = _closest_command_names(raw_cmd)
        suffix = ''
        if suggestion_text:
            rendered_suggestions = ' or '.join(
                f'`{item}`' for item in suggestion_text
            )
            suffix = f' Try {rendered_suggestions}.'
        self._renderer.add_system_message(
            f'Unknown command: {raw_cmd}.{suffix} Press Tab after `/` for autocomplete.',
            title='warning',
        )

    def _cmd_exit(self, parsed) -> bool:
        del parsed
        if self._renderer is not None:
            self._renderer.add_system_message('Goodbye.', title='grinta')
        return False

    def _cmd_settings(self, parsed) -> bool:
        del parsed
        if self._renderer is not None:
            with self._renderer.suspend_live():
                open_settings(self._console)
        else:
            open_settings(self._console)
        self._config = load_app_config()
        self._hud.update_model(get_current_model(self._config))
        if self._renderer is not None:
            self._renderer.set_cli_tool_icons(self._config.cli_tool_icons)
        # Don't add_system_message — settings are navigational, not part of
        # the agentic conversation and should not appear in chat history.
        return True

    def _cmd_clear(self, parsed) -> bool:
        if self._reject_extra_args(parsed):
            return True
        if self._renderer is not None:
            self._renderer.clear_history()
            self._renderer.add_system_message(
                'Screen cleared. Type a task or press Tab after `/` for commands.',
                title='grinta',
            )
        return True

    def _cmd_status(self, parsed) -> bool:
        verbose = False
        if parsed.args:
            arg = parsed.args[0].strip().lower()
            if arg in ('-v', '--verbose', 'verbose', 'v', 'full'):
                verbose = True
            else:
                self._warn(f'Usage: {self._usage(parsed.name)}')
                return True
            if len(parsed.args) > 1:
                self._warn(f'Usage: {self._usage(parsed.name)}')
                return True
        if self._renderer is None:
            return True
        body = self._hud.plain_text()
        if verbose:
            body = body + '\n\n' + self._build_status_diagnostics()
        self._renderer.add_system_message(body, title='status')
        return True

    def _build_status_diagnostics(self) -> str:
        """Best-effort runtime diagnostics for ``/status verbose``.

        All attribute accesses are wrapped \u2014 if any subsystem isn't wired up
        yet (no active controller, no breaker, etc.) the line is shown as
        ``n/a`` rather than raising.
        """
        import os

        lines: list[str] = ['Diagnostics:']

        controller = self._controller
        breaker_state = 'n/a'
        consecutive_errors: int | str = 'n/a'
        error_rate: float | str = 'n/a'
        if controller is not None:
            breaker = getattr(controller, 'circuit_breaker', None)
            if breaker is not None:
                consecutive_errors = getattr(breaker, 'consecutive_errors', 'n/a')
                try:
                    error_rate = round(float(breaker._calculate_error_rate()), 3)
                except Exception:
                    error_rate = 'n/a'
                breaker_state = (
                    'tripped'
                    if isinstance(consecutive_errors, int)
                    and consecutive_errors >= getattr(
                        getattr(breaker, 'config', None),
                        'max_consecutive_errors',
                        10**9,
                    )
                    else 'closed'
                )
        lines.append(
            f'  circuit_breaker: state={breaker_state} '
            f'consecutive_errors={consecutive_errors} error_rate={error_rate}'
        )

        event_stream_depth: int | str = 'n/a'
        if controller is not None:
            stream = getattr(controller, 'event_stream', None) or getattr(
                controller, '_event_stream', None
            )
            if stream is not None:
                queue = getattr(stream, '_queue', None)
                if queue is not None:
                    try:
                        event_stream_depth = queue.qsize()
                    except Exception:
                        event_stream_depth = 'n/a'
        lines.append(f'  event_stream_queue_depth: {event_stream_depth}')

        checkpoint_count: int | str = 'n/a'
        if controller is not None:
            ckpt_mgr = getattr(controller, 'checkpoint_manager', None)
            if ckpt_mgr is not None:
                checkpoints = getattr(ckpt_mgr, 'checkpoints', None) or getattr(
                    ckpt_mgr, '_checkpoints', None
                )
                try:
                    if checkpoints is not None:
                        checkpoint_count = len(checkpoints)
                except Exception:
                    checkpoint_count = 'n/a'
        lines.append(f'  checkpoints: {checkpoint_count}')

        condensation_count: int | str = 'n/a'
        if controller is not None:
            state_obj = getattr(controller, 'state', None)
            if state_obj is not None:
                condensation_count = getattr(
                    state_obj, 'condensation_count', 'n/a'
                )
        lines.append(f'  condensation_events: {condensation_count}')

        hud = self._hud.state
        lines.append(
            f'  cost: ${hud.cost_usd:.4f} ({hud.context_tokens:,} ctx tokens, '
            f'{hud.llm_calls} LLM calls)'
        )

        tracing_optout = any(
            os.getenv(var, '').strip().lower() in ('1', 'true', 'yes', 'on')
            for var in ('DO_NOT_TRACK', 'GRINTA_DISABLE_METRICS')
        )
        tracing_enabled_env = (
            os.getenv('TRACING_ENABLED', 'true').lower() == 'true'
            and not tracing_optout
        )
        lines.append(
            f'  tracing: enabled={tracing_enabled_env} '
            f'opt_out_env={tracing_optout}'
        )

        return '\n'.join(lines)

    def _cmd_cost(self, parsed) -> bool:
        if self._reject_extra_args(parsed):
            return True
        hud = self._hud.state
        tokens = (
            f'{hud.context_tokens:,} ctx · {hud.llm_calls} LLM calls'
            if hud.llm_calls
            else 'no LLM calls yet'
        )
        msg = (
            f'Session cost: ${hud.cost_usd:.4f}  ·  {tokens}\n'
            f'Model: {hud.model}'
        )
        if self._renderer is not None:
            self._renderer.add_system_message(msg, title='cost')
        return True

    def _cmd_diff(self, parsed) -> bool:
        parsed_diff = self._parse_diff_args(parsed)
        if parsed_diff is None:
            return True
        mode, paths = parsed_diff
        cwd = self._command_project_root()
        git_args = self._build_diff_git_args(mode, paths)
        body = self._run_git_diff(git_args, cwd)
        if body is None:
            return True
        if self._renderer is not None:
            self._renderer.add_system_message(body, title='diff')
        return True

    @staticmethod
    def _build_diff_git_args(mode: str, paths: list[str]) -> list[str]:
        git_args = ['git', 'diff']
        if mode != '--patch':
            git_args.append(mode)
        if paths:
            git_args.extend(['--', paths[0]])
        return git_args

    def _run_git_diff(self, git_args: list[str], cwd: Path) -> str | None:
        try:
            completed = subprocess.run(
                git_args,
                capture_output=True,
                text=True,
                cwd=cwd,
                check=False,
            )
        except FileNotFoundError:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    '`git` not found on PATH; cannot show diff.',
                    title='warning',
                )
            return None
        body = (completed.stdout or '').strip() or '(no changes)'
        if completed.stderr and completed.returncode != 0:
            body = (
                f'git diff failed in {cwd}\n\n'
                f'{completed.stderr.strip() or body}'
            )
        return body

    def _parse_diff_args(
        self, parsed,
    ) -> tuple[str, list[str]] | None:
        mode = '--stat'
        paths: list[str] = []
        for arg in parsed.args:
            if arg in {'--stat', '--name-only', '--patch'}:
                mode = arg
                continue
            if arg.startswith('-'):
                self._warn(f'Usage: {self._usage(parsed.name)}')
                return None
            paths.append(arg)
        if len(paths) > 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return None
        return mode, paths

    def _cmd_think(self, parsed) -> bool:
        cur = bool(getattr(self._config, 'enable_think', False))
        if len(parsed.args) > 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        new_val = self._resolve_think_value(parsed, cur)
        if new_val is None:
            return True
        try:
            self._config.enable_think = new_val  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'`think` tool now {"ON" if new_val else "OFF"} (applies to next system-prompt build).',
                title='think',
            )
        return True

    def _resolve_think_value(
        self, parsed, cur: bool,
    ) -> bool | None:
        if not parsed.args:
            return not cur
        target = parsed.args[0].lower()
        if target in ('on', 'true', '1', 'yes'):
            return True
        if target in ('off', 'false', '0', 'no'):
            return False
        if self._renderer is not None:
            self._renderer.add_system_message(
                'Usage: /think [on|off]', title='warning'
            )
        return None

    def _cmd_checkpoint(self, parsed) -> bool:
        args = list(parsed.args)
        sub = args[0].lower() if args else ''
        if sub in {'list', 'ls'}:
            self._handle_checkpoint_list(args[1:])
            return True
        if sub == 'diff':
            self._handle_checkpoint_diff(args[1:])
            return True
        label = ' '.join(args).strip()
        instruction = (
            'Use the `checkpoint` tool now to snapshot the current workspace state.'
        )
        if label:
            instruction += f' Use this label: {label}'
        self._next_action = MessageAction(content=instruction)
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Checkpoint queued{(" (" + label + ")") if label else ""}.',
                title='checkpoint',
            )
        return True

    def _cmd_copy(self, parsed) -> bool:
        from backend.cli.repl import _copy_to_system_clipboard

        if self._reject_extra_args(parsed):
            return True
        last_reply = (
            self._renderer.last_assistant_message_text
            if self._renderer is not None
            else ''
        )
        ok, msg = _copy_to_system_clipboard(last_reply)
        if self._renderer is not None:
            self._renderer.add_system_message(
                msg, title='clipboard' if ok else 'warning'
            )
        return True

    def _cmd_sessions(self, parsed) -> bool:
        from backend.cli.session_manager import list_sessions

        args = list(parsed.args)
        if args and args[0].lower() == 'list':
            args.pop(0)
        if len(args) > 1:
            self._warn('Usage: /sessions [list] [limit]')
            return True
        limit = 20
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                self._warn('Usage: /sessions [list] [limit]')
                return True
            if limit < 1:
                self._warn('Session limit must be 1 or greater.')
                return True
        if self._renderer is not None:
            with self._renderer.suspend_live():
                list_sessions(self._console, limit=limit, config=self._config)
        else:
            list_sessions(self._console, limit=limit, config=self._config)
        return True

    def _cmd_resume(self, parsed) -> bool:
        if len(parsed.args) != 1:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Usage: /resume <N> or /resume <session_id>. Press Tab to autocomplete recent sessions.',
                    title='warning',
                )
            return True
        self._pending_resume = parsed.args[0]
        return True

    def _cmd_autonomy(self, parsed) -> bool:
        self._handle_autonomy_command(parsed)
        return True

    def _cmd_help(self, parsed) -> bool:
        from backend.cli.repl import _build_help_markdown

        if len(parsed.args) > 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        if self._renderer is not None:
            self._renderer.add_markdown_block(
                'Help',
                _build_help_markdown(parsed.args[0] if parsed.args else None),
            )
        return True

    def _cmd_model(self, parsed) -> bool:
        from backend.cli.config_manager import update_model

        if not parsed.args:
            current = get_current_model(self._config)
            provider, model = HUDBar.describe_model(current)
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f'Current provider: {provider}  model: {model}  (use `/model <provider/model>` to switch)',
                    title='model',
                )
            return True
        if len(parsed.args) != 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        new_model = parsed.args[0].strip()
        if (
            '/' not in new_model
            or new_model.startswith('/')
            or new_model.endswith('/')
        ):
            self._warn(
                'Use a provider-qualified model, for example `openai/gpt-4.1`.'
            )
            return True
        update_model(new_model)
        self._config = load_app_config()
        self._hud.update_model(get_current_model(self._config))
        provider, model = HUDBar.describe_model(get_current_model(self._config))
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Model switched to provider: {provider}  model: {model}. Changes apply to the next session.',
                title='model',
            )
        return True

    def _cmd_compact(self, parsed) -> bool:
        if self._reject_extra_args(parsed):
            return True
        from backend.ledger.action.agent import CondensationRequestAction

        self._next_action = CondensationRequestAction()
        return True

    def _cmd_retry(self, parsed) -> bool:
        if self._reject_extra_args(parsed):
            return True
        if self._last_user_message:
            self._next_action = MessageAction(content=self._last_user_message)
        else:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'No previous message to retry.',
                    title='warning',
                )
        return True
