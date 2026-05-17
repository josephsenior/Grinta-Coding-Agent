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
from typing import TYPE_CHECKING, Any, cast

from backend.cli._typing import SlashCommandsHost
from backend.cli.config_manager import get_current_model
from backend.cli.hud import HUDBar
from backend.cli.settings_tui import open_settings
from backend.core.config import load_app_config
from backend.ledger.action import MessageAction

if TYPE_CHECKING:
    from rich.console import Console

    from backend.core.config import AppConfig


def _command_project_root_from_host(host: SlashCommandsHost) -> Path:
    return host._command_project_root()


def _parse_diff_args_from_host(
    host: SlashCommandsHost,
    parsed: Any,
) -> tuple[str, list[str]] | None:
    return host._parse_diff_args(parsed)


def _run_git_diff_from_host(
    host: SlashCommandsHost,
    git_args: list[str],
    cwd: Path,
) -> str | None:
    return host._run_git_diff(git_args, cwd)


class SlashCommandsMixin:
    """Mixin providing the slash-command surface of the REPL."""

    # Attributes provided by the concrete ``backend.cli.repl.Repl`` host class.
    # Declared here so the mixin's references type-check without forcing each
    # call site to carry an ``# type: ignore[attr-defined]``.
    if TYPE_CHECKING:
        _renderer: Any | None
        _console: Console
        _config: AppConfig
        _hud: HUDBar
        _controller: Any | None
        _event_stream: Any | None
        _next_action: Any | None
        _pending_resume: str | None
        _last_user_message: str | None

        def _warn(self, msg: str) -> None: ...
        def _usage(self, name: str) -> str: ...
        def _reject_extra_args(self, parsed: Any) -> bool: ...
        def _command_project_root(self) -> Path: ...

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
        entries = sorted(entries, key=lambda e: e.get('timestamp', 0), reverse=True)[
            :limit
        ]
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
            f'  {e.get("id", "?")[:12]:<12} {ts_str}  '
            f'{e.get("checkpoint_type", "?"):<18} {e.get("description", "")[:60]}'
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
            match.get('git_commit_sha'),
            manager.workspace_path,
        )
        if self._renderer is not None:
            # Trim to keep the panel manageable.
            if len(diff_text) > 8000:
                diff_text = diff_text[:8000] + '\n[... diff truncated ...]\n'
            self._renderer.add_markdown_block(
                f'checkpoint diff {match.get("id", "?")[:12]}',
                f'```diff\n{diff_text}\n```',
            )

    def _find_checkpoint_match(
        self,
        manager: Any,
        cp_id: str,
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
        sha: Any,
        workspace_path: Any,
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
            f'  {name:<10} — {_AUTONOMY_LEVEL_HINTS[name]}' for name in valid_levels
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
        '/checkpoint': '_cmd_checkpoint',
        '/copy': '_cmd_copy',
        '/search': '_cmd_search',
        '/sessions': '_cmd_sessions',
        '/resume': '_cmd_resume',
        '/autonomy': '_cmd_autonomy',
        '/help': '_cmd_help',
        '/model': '_cmd_model',
        '/compact': '_cmd_compact',
        '/retry': '_cmd_retry',
        '/health': '_cmd_health',
        '/add_repo_inst': '_cmd_playbook_passthrough',
        '/address_pr_comments': '_cmd_playbook_passthrough',
        '/api': '_cmd_playbook_passthrough',
        '/audit': '_cmd_playbook_passthrough',
        '/ci': '_cmd_playbook_passthrough',
        '/codereview': '_cmd_playbook_passthrough',
        '/codereview-roasted': '_cmd_playbook_passthrough',
        '/compress': '_cmd_playbook_passthrough',
        '/database': '_cmd_playbook_passthrough',
        '/debug': '_cmd_playbook_passthrough',
        '/docs': '_cmd_playbook_passthrough',
        '/feature': '_cmd_playbook_passthrough',
        '/hardened': '_cmd_playbook_passthrough',
        '/orch-debug': '_cmd_playbook_passthrough',
        '/owasp': '_cmd_playbook_passthrough',
        '/perf': '_cmd_playbook_passthrough',
        '/react': '_cmd_playbook_passthrough',
        '/recover': '_cmd_playbook_passthrough',
        '/refactor': '_cmd_playbook_passthrough',
        '/release': '_cmd_playbook_passthrough',
        '/remember': '_cmd_playbook_passthrough',
        '/security': '_cmd_playbook_passthrough',
        '/testing': '_cmd_playbook_passthrough',
        '/tool': '_cmd_playbook_passthrough',
        '/update_pr_description': '_cmd_playbook_passthrough',
        '/update_test': '_cmd_playbook_passthrough',
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
            rendered_suggestions = ' or '.join(f'`{item}`' for item in suggestion_text)
            suffix = f' Did you mean {rendered_suggestions}?'
        self._renderer.add_system_message(
            f'Unknown command: `{raw_cmd}`.{suffix}\n'
            'Type `/help` to list commands, or press Tab after `/` to autocomplete.',
            title='warning',
        )

    def _cmd_exit(self, parsed) -> bool:
        del parsed
        if self._renderer is not None:
            hud = self._hud.state
            parts = []
            if hud.context_tokens > 0 or hud.llm_calls > 0:
                parts.append(f'{hud.llm_calls} LLM calls')
                parts.append(f'{hud.context_tokens:,} tokens')
                if hud.cost_usd > 0:
                    parts.append(f'${hud.cost_usd:.4f}')
                if hud.condensation_count > 0:
                    parts.append(f'{hud.condensation_count}x condensed')
                summary = ' · '.join(parts)
                self._renderer.add_system_message(summary, title='session')
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
                'Transcript cleared. Send a message, or type `/help` for commands.',
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
                    and consecutive_errors
                    >= getattr(
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
            monitor = getattr(controller, 'memory_pressure', None)
            if monitor is not None:
                condensation_count = monitor._condensation_count
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
            f'  tracing: enabled={tracing_enabled_env} opt_out_env={tracing_optout}'
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
        msg = f'Session cost: ${hud.cost_usd:.4f}  ·  {tokens}\nModel: {hud.model}'
        if self._renderer is not None:
            self._renderer.add_system_message(msg, title='cost')
        return True

    def _cmd_health(self, parsed) -> bool:
        """Run a fast self-check.

        Verifies provider reachable, debugpy importable, ripgrep + git
        available.
        """
        if self._reject_extra_args(parsed):
            return True
        import shutil

        checks: list[tuple[str, bool, str]] = []

        try:
            import importlib

            importlib.import_module('debugpy.adapter')
            checks.append(('debugpy', True, 'importable'))
        except Exception as exc:
            checks.append(('debugpy', False, f'import failed: {exc}'))

        for binary in ('rg', 'git'):
            path = shutil.which(binary)
            checks.append((binary, path is not None, path or 'not found on PATH'))

        hud = self._hud.state
        checks.append(('model', bool(hud.model), hud.model or 'not set'))

        lines = ['Self-check:']
        for name, ok, detail in checks:
            mark = 'ok ' if ok else 'FAIL'
            lines.append(f'  [{mark}] {name}: {detail}')

        if self._renderer is not None:
            self._renderer.add_system_message('\n'.join(lines), title='health')
        return True

    def _cmd_diff(self, parsed) -> bool:
        host = cast(SlashCommandsHost, self)
        parsed_diff = _parse_diff_args_from_host(host, parsed)
        if not isinstance(parsed_diff, tuple) or len(parsed_diff) != 2:
            return True  # type: ignore[unreachable]
        mode, paths = parsed_diff
        cwd = _command_project_root_from_host(host)
        git_args = self._build_diff_git_args(mode, paths)
        body = _run_git_diff_from_host(host, git_args, cwd)
        if body is None:
            return True
        if self._renderer is not None:
            if mode == '--patch' and body not in ('(no changes)', ''):
                self._renderer_render_diff(self._renderer, body)
            else:
                self._renderer.add_system_message(body, title='diff')
        return True

    def _renderer_render_diff(self, renderer: Any, diff_body: str) -> None:
        """Render a patch diff with per-file foldable sections."""
        from rich import box
        from rich.panel import Panel
        from rich.syntax import Syntax
        from rich.text import Text

        from backend.cli.theme import CLR_CARD_BORDER, CLR_CARD_TITLE

        files = self._parse_diff_files(diff_body)

        file_count = len(files)
        total_added = sum(f['added'] for f in files)
        total_removed = sum(f['removed'] for f in files)

        summary = f'{file_count} file{"s" if file_count != 1 else ""} changed'
        if total_added > 0 or total_removed > 0:
            inserts = f'+{total_added}' if total_added > 0 else ''
            deletes = f'-{total_removed}' if total_removed > 0 else ''
            summary += f'  ({inserts}{", " if inserts and deletes else ""}{deletes})'

        if file_count == 1:
            syntax = Syntax(
                diff_body,
                lexer='diff',
                theme='monokai',
                word_wrap=True,
                padding=(1, 2),
                background_color='default',
                line_numbers=True,
            )
            renderer.add_system_message(f'{summary}\n\n{syntax}', title='diff')
            return

        # Multi-file: render each file as its own panel
        renderer.add_system_message(summary, title='diff')
        for f in files:
            file_diff = '\n'.join(f['lines'])
            file_label = f['path']
            add_str = f'+{f["added"]}' if f['added'] > 0 else ''
            rem_str = f'-{f["removed"]}' if f['removed'] > 0 else ''
            delta = ''
            if add_str or rem_str:
                delta = f'  ({add_str}{", " if add_str and rem_str else ""}{rem_str})'

            syntax = Syntax(
                file_diff,
                lexer='diff',
                theme='monokai',
                word_wrap=True,
                padding=(1, 2),
                background_color='default',
                line_numbers=True,
            )
            panel = Panel(
                syntax,
                title=Text(f'{file_label}{delta}', style=CLR_CARD_TITLE),
                title_align='left',
                border_style=CLR_CARD_BORDER,
                box=box.ROUNDED,
                padding=(0, 1),
            )
            if hasattr(renderer, 'add_renderable'):
                renderer.add_renderable(panel)
            else:
                renderer.add_system_message(
                    f'[{file_label}]{delta}[/]\n\n{file_diff}',
                    title='diff',
                )

    @staticmethod
    def _parse_diff_files(diff_body: str) -> list[dict]:
        """Split a unified diff into per-file sections.

        Returns a list of dicts with keys: ``path``, ``lines``, ``added``, ``removed``.
        """
        import re

        files: list[dict] = []
        current: list[str] = []
        current_path = ''
        added = 0
        removed = 0

        for line in diff_body.split('\n'):
            if line.startswith('diff --git'):
                if current and current_path:
                    files.append(
                        {
                            'path': current_path,
                            'lines': current,
                            'added': added,
                            'removed': removed,
                        }
                    )
                current = [line]
                current_path = ''
                added = 0
                removed = 0
                m = re.match(r'diff --git a/(.*) b/.*', line)
                if m:
                    current_path = m.group(1)
            else:
                current.append(line)
                if line.startswith('+') and not line.startswith('+++'):
                    added += 1
                elif line.startswith('-') and not line.startswith('---'):
                    removed += 1

        if current and current_path:
            files.append(
                {
                    'path': current_path,
                    'lines': current,
                    'added': added,
                    'removed': removed,
                }
            )

        return files

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
            body = f'git diff failed in {cwd}\n\n{completed.stderr.strip() or body}'
        return body

    def _parse_diff_args(
        self,
        parsed,
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
        if not last_reply.strip():
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'No assistant reply available to copy yet.',
                    title='warning',
                )
            return True
        ok, msg = _copy_to_system_clipboard(last_reply)
        if self._renderer is not None:
            if ok:
                char_count = len(last_reply.strip())
                line_count = last_reply.strip().count('\n') + 1
                self._renderer.add_system_message(
                    f'Copied {char_count} characters ({line_count} lines) to clipboard.',
                    title='clipboard',
                )
            else:
                self._renderer.add_system_message(msg, title='warning')
        return True

    def _cmd_search(self, parsed) -> bool:
        """Search the current session transcript for matching text."""
        query = ' '.join(parsed.args).strip()
        if not query:
            self._warn('Usage: /search <text to find>')
            return True
        if self._event_stream is None:
            self._warn('No active session to search.')
            return True
        if self._renderer is None:
            self._warn('Renderer not available.')
            return True

        from rich import box
        from rich.table import Table

        from backend.cli.theme import CLR_BRAND, CLR_CARD_BORDER, CLR_META, STYLE_DIM

        try:
            events = self._event_stream.get_matching_events(
                query=query, limit=20, reverse=True
            )
        except Exception:
            self._warn('Search failed. See logs for details.')
            return True

        if not events:
            self._renderer.add_system_message(
                f'No results found for "{query}".', title='search'
            )
            return True

        table = Table(
            show_header=True,
            header_style=f'bold {CLR_BRAND}',
            box=box.SIMPLE,
            pad_edge=False,
            show_lines=False,
        )
        table.add_column('#', style=STYLE_DIM, width=6, justify='right')
        table.add_column('Type', style=CLR_META, width=18)
        table.add_column('Preview', style=CLR_CARD_BORDER, overflow='fold')

        for evt in events:
            evt_type = (
                type(evt).__name__.replace('Action', '').replace('Observation', '')
            )
            content = getattr(evt, 'content', '') or getattr(evt, 'message', '') or ''
            preview = content.strip()[:120].replace('\n', ' ')
            table.add_row(str(getattr(evt, 'id', '?')), evt_type, preview)

        self._renderer.add_system_message(
            table, title=f'search: "{query}" ({len(events)} results)'
        )
        return True

    def _cmd_sessions(self, parsed) -> bool:
        from backend.cli.session_manager import (
            delete_sessions,
            list_sessions,
            show_session,
        )

        args = list(parsed.args)
        if args and args[0].lower() == 'list':
            args.pop(0)

        search = None
        sort_by = 'updated'
        limit = 20
        preview_idx = None
        delete_targets: list[str] = []

        i = 0
        while i < len(args):
            a = args[i]
            if a in ('--search', '-s') and i + 1 < len(args):
                search = args[i + 1]
                i += 2
            elif a in ('--sort',) and i + 1 < len(args):
                allowed = ('updated', 'created', 'events', 'cost', 'model')
                if args[i + 1] in allowed:
                    sort_by = args[i + 1]
                else:
                    self._warn(f'Sort must be one of: {", ".join(allowed)}')
                    return True
                i += 2
            elif a in ('--delete', '-d') and i + 1 < len(args):
                i += 1
                while i < len(args) and not args[i].startswith('-'):
                    delete_targets.append(args[i])
                    i += 1
            elif a in ('--limit', '-l') and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    self._warn('Limit must be a number.')
                    return True
                if limit < 1:
                    self._warn('Limit must be 1 or greater.')
                    return True
                i += 2
            elif a == '--preview' and i + 1 < len(args):
                preview_idx = args[i + 1]
                i += 2
            else:
                # Positional: session limit (use --preview <N> for preview)
                try:
                    parsed_limit = int(a)
                except ValueError:
                    self._warn(f'Unknown option: {a}')
                    return True
                if parsed_limit < 1:
                    self._warn('Limit must be 1 or greater.')
                    return True
                limit = parsed_limit
                i += 1

        if delete_targets:
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    delete_sessions(self._console, delete_targets, config=self._config)
            else:
                delete_sessions(self._console, delete_targets, config=self._config)
            return True

        if preview_idx is not None:
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    found = show_session(
                        self._console, config=self._config, target=preview_idx
                    )
                    if not found:
                        self._warn(f"No session at '{preview_idx}'")
            else:
                found = show_session(
                    self._console, config=self._config, target=preview_idx
                )
                if not found:
                    self._warn(f"No session at '{preview_idx}'")
            return True

        if self._renderer is not None:
            with self._renderer.suspend_live():
                list_sessions(
                    self._console,
                    limit=limit,
                    config=self._config,
                    sort_by=sort_by,
                    search=search,
                )
        else:
            list_sessions(
                self._console,
                limit=limit,
                config=self._config,
                sort_by=sort_by,
                search=search,
            )
        return True

    def _cmd_resume(self, parsed) -> bool:
        if len(parsed.args) != 1:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Usage: `/resume <N>` or `/resume <session_id>`.\n'
                    'Press Tab after `/resume ` to autocomplete recent sessions.',
                    title='warning',
                )
            return True
        self._pending_resume = parsed.args[0]
        return True

    def _cmd_autonomy(self, parsed) -> bool:
        self._handle_autonomy_command(parsed)
        return True

    def _cmd_help(self, parsed) -> bool:
        from backend.cli.repl import _build_help_markdown, _build_help_table

        if len(parsed.args) > 1:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True

        search_term = None
        show_all = False

        if parsed.args:
            arg = parsed.args[0]
            if arg in ('--all', '-a'):
                show_all = True
            elif arg not in ('--search', '-s'):
                # Specific command requested
                help_text = _build_help_markdown(arg)
                if self._renderer is not None:
                    self._renderer.add_markdown_block(
                        'Help',
                        help_text,
                    )
                return True

        # Check for search flag
        if parsed.args and parsed.args[0] in ('--search', '-s'):
            search_term = parsed.args[1] if len(parsed.args) > 1 else None

        # Show interactive table (if renderer supports add_renderable)
        table = _build_help_table(search_term, show_all=show_all)
        if self._renderer is not None:
            if hasattr(self._renderer, 'add_renderable'):
                self._renderer.add_renderable(table, force_terminal=True)
            else:
                # Fallback: convert table to string and show as markdown
                from io import StringIO

                from rich.console import Console

                sio = StringIO()
                table_console = Console(file=sio, force_terminal=True, width=100)
                table_console.print(table)
                self._renderer.add_system_message(sio.getvalue().strip(), title='help')
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
        if '/' not in new_model or new_model.startswith('/') or new_model.endswith('/'):
            self._warn('Use a provider-qualified model, for example `openai/gpt-4.1`.')
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

    def _cmd_playbook_passthrough(self, parsed) -> bool:
        """Queue a playbook slash command as a normal user turn.

        Playbook slash triggers are matched by memory-level trigger logic, not
        by the REPL command handler itself.
        """
        suffix = f' {" ".join(parsed.args)}' if parsed.args else ''
        self._next_action = MessageAction(content=f'{parsed.name}{suffix}')
        return True
