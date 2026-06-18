"""Async REPL — prompt_toolkit input loop integrated with the agent engine.

Slash-command registry lives in :mod:`backend.cli.repl.slash_command_registry`.
Import registry helpers from there, not from this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from rich.console import Console

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.display.status_chrome import (
    autonomy_chrome_suffix,
    status_fields_from_hud,
)
from backend.cli.repl.run_helpers_mixin import RunHelpersMixin
from backend.cli.repl.session_lifecycle_mixin import SessionLifecycleMixin
from backend.cli.repl.slash_commands_mixin import SlashCommandsMixin
from backend.cli.settings import get_current_model
from backend.cli.theme import CLR_STATUS_ERR, mark_prompt, prompt_toolkit_style_dict
from backend.core.config import (
    AppConfig,
)
from backend.core.config import (
    load_app_config as load_app_config,  # re-exported for tests/back-compat
)
from backend.core.enums import AgentState

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from backend.ledger.stream import EventStream

# Slash-command registry (used by Repl only — import from registry elsewhere).
from backend.cli.repl.slash_command_registry import (  # noqa: F401
    _AUTONOMY_LEVEL_HINTS,
    _COMMAND_ALIASES,
    _COMMAND_NAMES,
    _CSI_OSC_DCS,
    _HELP_INPUT_TIPS,
    _HELP_SECTION_COLLAPSE_THRESHOLD,
    _HELP_SECTIONS_ORDER,
    _HISTORY_DIR,
    _HISTORY_FILE,
    _KNOWN_MODELS,
    _ORPHAN_BRACKET_CSI,
    _ORPHAN_PARAM_CHUNK_SINGLE,
    _ORPHAN_PARAM_CHUNK_STREAM,
    _PLAYBOOK_SLASH_COMMANDS,
    _SLASH_COMMANDS,
    ParsedSlashCommand,
    SlashCommandParseError,
    SlashCommandSpec,
    _attach_prompt_buffer_csi_sanitizer,
    _build_bindings,
    _build_command_completer,
    _build_help_markdown,
    _build_help_table,
    _build_help_table_fallback,
    _canonical_command_name,
    _closest_command_names,
    _copy_to_system_clipboard,
    _ensure_history,
    _find_command_spec,
    _help_for_specific_command,
    _help_section_lines,
    _iter_command_completion_entries,
    _looks_like_terminal_selection_noise,
    _parse_slash_command,
    _prompt_toolkit_available,
    _split_command_words,
    _strip_leaked_terminal_artifacts,
    _supports_prompt_session,
)

# ---------------------------------------------------------------------------
# REPL class
# ---------------------------------------------------------------------------


class Repl(SlashCommandsMixin, SessionLifecycleMixin, RunHelpersMixin):
    """Interactive REPL that drives an in-process agent session."""

    def __init__(self, config: AppConfig, console: Console) -> None:
        self._config = config
        self._console = console
        self._hud = HUDBar()
        # Enable minimal mode if flag was passed
        if getattr(config, '_minimal_mode', False):
            self._hud.set_minimal_mode(True)
        # Enable accessible mode if flag was passed
        if getattr(config, '_accessible_mode', False):
            self._hud.set_minimal_mode(True)
        self._reasoning = ReasoningDisplay()
        self._renderer: Any | None = None
        self._event_stream: EventStream | None = None
        self._controller: Any | None = None
        self._running = True
        # Bootstrap components (stored for session resume).
        self._agent: Any | None = None
        self._runtime: Any | None = None
        self._memory: Any | None = None
        self._llm_registry: Any | None = None
        self._conversation_stats: Any | None = None
        self._acquire_result: Any | None = None
        self._pending_resume: str | None = None
        self._next_action: Any | None = None
        self._last_user_message: str | None = None
        self._queued_input: list[str] = []
        #: Single-line bootstrap / idle status under the stats bar (prompt_toolkit only).
        self._footer_system_status: str = ''
        self._footer_system_kind: str = 'system'
        self._pt_session: Any | None = None
        #: Shown once per REPL run when Ctrl+C is pressed at the input prompt.
        self._prompt_ctrl_c_hint_shown: bool = False
        #: When True, LOW-risk actions are auto-approved without prompt.
        self._suppress_low_risk_confirmations: bool = False
        #: Circuit breaker: consecutive prompt input failures.
        self._consecutive_input_failures: int = 0

    def _invalidate_pt(self) -> None:
        sess = self._pt_session
        if sess is None:
            return
        app = getattr(sess, 'app', None)
        if app is not None:
            app.invalidate()

    def _sync_terminal_after_agent_turn(self, session: Any | None) -> None:
        """Restore sane stdout/stderr after Rich Live so the next prompt can paint.

        While the agent runs, ``prompt_toolkit`` is idle (``app._is_running`` is
        false), so ``Application.invalidate()`` is a no-op. Rich may leave the
        cursor hidden or streams unsynced — without this, the multiline prompt
        sometimes never appears until the user resizes the terminal.
        """
        if session is None:
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        try:
            self._console.show_cursor(True)
        except Exception:
            pass
        out = getattr(session, 'output', None)
        if out is not None:
            try:
                # Leave the cursor on a fresh row after Rich scrollback so the
                # next full-screen prompt layout computes correctly.
                out.write('\n')
                out.flush()
            except Exception:
                pass

    def _set_footer_system_line(self, text: str, *, kind: str = 'system') -> None:
        """One shared status line under the stats bar; replaces previous text."""
        self._footer_system_status = text
        self._footer_system_kind = kind
        self._invalidate_pt()

    def _append_footer_system_fragments(
        self,
        fragments: list[tuple[str, str]],
        add: Callable[[str, str], None],
    ) -> None:
        status = self._footer_system_status.strip()
        if not status:
            return
        warn = self._footer_system_kind.strip().lower() == 'warning'
        body_cls = (
            'class:prompt.footer.warn_body' if warn else 'class:prompt.footer.body'
        )
        label = 'system'
        sep = ': '
        cols = shutil.get_terminal_size((110, 24)).columns
        reserve = 5 + len(label) + len(sep)
        max_w = max(16, cols - reserve)
        if len(status) > max_w:
            status = status[: max_w - 1] + '…'
        add('', '\n')
        if warn:
            add('class:prompt.footer.warn_bracket', '[')
            add('class:prompt.footer.warn_core', '!')
            add('class:prompt.footer.warn_bracket', ']  ')
            add('class:prompt.footer.warn_kicker', label)
            add('class:prompt.footer.warn_sep', sep)
        else:
            add('class:prompt.footer.badge_bracket', '[')
            add('class:prompt.footer.badge_core', 'i')
            add('class:prompt.footer.badge_bracket', ']  ')
            add('class:prompt.footer.kicker', label)
            add('class:prompt.footer.sep', sep)
        add(body_cls, status)

    @property
    def pending_resume(self) -> str | None:
        return self._pending_resume

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = renderer

    def set_controller(self, controller: Any) -> None:
        self._controller = controller

    def set_bootstrap_state(
        self,
        *,
        agent: Any | None = None,
        runtime: Any | None = None,
        memory: Any | None = None,
        llm_registry: Any | None = None,
        conversation_stats: Any | None = None,
        event_stream: Any | None = None,
        acquire_result: Any | None = None,
    ) -> None:
        if agent is not None:
            self._agent = agent
        if runtime is not None:
            self._runtime = runtime
        if memory is not None:
            self._memory = memory
        if llm_registry is not None:
            self._llm_registry = llm_registry
        if conversation_stats is not None:
            self._conversation_stats = conversation_stats
        if event_stream is not None:
            self._event_stream = event_stream
        if acquire_result is not None:
            self._acquire_result = acquire_result

    def queue_initial_input(self, text: str) -> None:
        if text:
            self._queued_input.append(text)

    def _current_prompt_state(self) -> AgentState | None:
        renderer = self._renderer
        state = (
            getattr(renderer, 'current_state', None) if renderer is not None else None
        )
        if isinstance(state, AgentState):
            return state

        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                candidate = controller.get_agent_state()
                if isinstance(candidate, AgentState):
                    return candidate
        return None

    def _prompt_message(self) -> str:
        state = self._current_prompt_state()
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            label = 'retry '
        else:
            label = ''
        return f'{label}{mark_prompt()} '

    def _prompt_placeholder(self) -> Any:
        from prompt_toolkit.formatted_text import FormattedText

        return FormattedText(
            [('class:placeholder', 'Describe the task, or type /help')]
        )

    def _prompt_state_label(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return 'Needs approval'
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return 'Needs attention'
        if state == AgentState.RUNNING:
            return 'Running'
        if state == AgentState.FINISHED:
            return 'Done'
        if state == AgentState.STOPPED:
            return 'Stopped'
        return 'Ready'

    def _prompt_autonomy_label(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                level = str(getattr(ac, 'autonomy_level', 'balanced')).strip().lower()
                if level in _AUTONOMY_LEVEL_HINTS:
                    return f'autonomy:{level}'
        return 'autonomy:balanced'

    def _prompt_panel_data(self) -> dict[str, str]:
        """Sync agent/autonomy labels into the HUD, then return telemetry dict."""
        hud = self._hud.state
        state_label = self._prompt_state_label()
        current_label = (hud.agent_state_label or '').strip()
        if not current_label.startswith(('Backoff', 'Retrying')):
            self._hud.update_agent_state(state_label)
        ac = (
            getattr(self._controller, 'autonomy_controller', None)
            if self._controller is not None
            else None
        )
        if ac is not None:
            level = str(getattr(ac, 'autonomy_level', 'balanced')).strip().lower()
            if level in _AUTONOMY_LEVEL_HINTS:
                self._hud.update_autonomy(level)
        fields = status_fields_from_hud(self._hud.state, self._hud.bundled_skill_count)
        mcp_txt = HUDBar._format_mcp_servers_label(hud.mcp_servers)
        skills_txt = HUDBar._format_skills_label(self._hud.bundled_skill_count)

        # Build token display with inline progress bar.
        from backend.cli.display.status_chrome import _token_bar

        has_limit = '/' in fields.token_display_compact
        if has_limit and fields.token_usage_pct > 0:
            token_with_bar = f'{_token_bar(fields.token_usage_pct, 4)} {fields.token_display_compact}'
        else:
            token_with_bar = fields.token_display_compact

        return {
            'state_label': fields.agent_state_label,
            'autonomy_label': autonomy_chrome_suffix(fields.autonomy_level),
            'workspace': fields.workspace_path,
            'provider': fields.provider,
            'model': fields.model,
            'token_display': token_with_bar,
            'cost': f'${fields.cost_usd:.3f}',
            'calls': f'{fields.llm_calls} calls',
            'mcp': mcp_txt,
            'skills': skills_txt,
            'ledger': fields.ledger_status,
        }

    def _prompt_state_style(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return 'class:prompt.badge.review'
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return 'class:prompt.badge.error'
        if state == AgentState.RUNNING:
            return 'class:prompt.badge.running'
        return 'class:prompt.badge.ready'

    def _prompt_autonomy_style(self) -> str:
        label = self._prompt_autonomy_label()
        if 'full' in label:
            return 'class:prompt.autonomy.full'
        if 'conservative' in label:
            return 'class:prompt.autonomy.conservative'
        return 'class:prompt.autonomy.balanced'

    @staticmethod
    def _prompt_ledger_style(ledger_status: str) -> str:
        if ledger_status in {'Healthy', 'Ready', 'Idle', 'Starting'}:
            return 'class:prompt.health.good'
        if ledger_status in {'Review', 'Paused'}:
            return 'class:prompt.health.warn'
        return 'class:prompt.health.bad'

    def _prompt_toolbar_text(self) -> str:
        data = self._prompt_panel_data()
        state_label = data['state_label']
        autonomy_label = data['autonomy_label']
        controls = f'{state_label}  │  {autonomy_label}  │  Tab for commands'
        telemetry = (
            f'provider: {data["provider"]}  │  model: {data["model"]}  │  {data["token_display"]}  │  {data["cost"]}  │  '
            f'{data["calls"]}  │  {data["mcp"]}  │  {data["skills"]}  │  {data["ledger"]}'
        )
        return f' {controls}\n {telemetry} '

    def _prompt_panel_message(self) -> Any:
        return [
            ('class:prompt.arrow', self._prompt_message()),
        ]

    def _create_prompt_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style

        from backend.cli.session.session_manager import get_session_suggestions

        prompt_style = Style.from_dict(prompt_toolkit_style_dict())

        return PromptSession(
            message=self._prompt_panel_message,
            history=FileHistory(str(_ensure_history())),
            key_bindings=_build_bindings(),
            completer=_build_command_completer(
                lambda: get_session_suggestions(self._config)
            ),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            reserve_space_for_menu=8,
            enable_history_search=True,
            multiline=True,
            mouse_support=False,
            style=prompt_style,
            erase_when_done=True,
            placeholder=self._prompt_placeholder,
        )

    async def ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        memory: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        ensure_controller_loop = cast(Any, self._ensure_controller_loop)
        return await ensure_controller_loop(
            controller=controller,
            agent_task=agent_task,
            create_controller=create_controller,
            create_status_callback=create_status_callback,
            run_agent_until_done=run_agent_until_done,
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            memory=memory,
            end_states=end_states,
        )

    async def cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        await self._cancel_agent(agent_task)

    async def resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        resume_session = cast(Any, self._resume_session)
        return await resume_session(
            target,
            config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def handle_autonomy_command(self, text: str) -> None:
        try:
            parsed = _parse_slash_command(text)
        except SlashCommandParseError as exc:
            self._warn(str(exc))
            return
        self._handle_autonomy_command(parsed)

    def handle_command(self, text: str) -> bool:
        return self._handle_command(text)

    def _warn(self, message: str, *, title: str = 'warning') -> None:
        if self._renderer is not None:
            self._renderer.add_system_message(message, title=title)

    def _usage(self, command_name: str) -> str:
        spec = _find_command_spec(command_name)
        return spec.usage if spec is not None else command_name

    def _reject_extra_args(self, parsed: ParsedSlashCommand) -> bool:
        if not parsed.args:
            return False
        self._warn(f'Usage: {self._usage(parsed.name)}')
        return True

    def _command_project_root(self) -> Path:
        raw_project = getattr(self._config, 'project_root', None)
        if isinstance(raw_project, str) and raw_project.strip():
            with contextlib.suppress(OSError):
                return Path(raw_project).expanduser().resolve()
        return Path.cwd().resolve()

    async def _read_non_interactive_input(self) -> str:
        if self._queued_input:
            return self._queued_input.pop(0)
        self._console.print('grinta> ', end='')
        return await asyncio.to_thread(sys.stdin.readline)

    # -- public entry point ------------------------------------------------

    async def run(self) -> None:
        """Boot the engine, subscribe to events, and loop on user input."""
        from backend.cli.repl.debug import debug as diag

        diag('run() ENTER')
        loop = asyncio.get_running_loop()
        agent_task: asyncio.Task | None = None
        bootstrap_task: asyncio.Task[None] | None = None

        # -- imports (always needed) ----------------------------------------
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.bootstrap.main import (
            _create_early_status_callback,
        )
        from backend.core.bootstrap.setup import create_controller

        try:
            config = self._config
            self._hud.update_model(get_current_model(config))
            self._hud.update_workspace(getattr(config, 'project_root', None))

            # -- prompt session (fast, no I/O) --------------------------------
            session = self._build_prompt_session()
            diag(
                f'run() session built: session={"PT" if session is not None else "None"}'
            )

            # -- renderer (no event-stream subscription yet) ------------------
            renderer = self._build_renderer(session, loop)

            # -- staged init runs in background while user sees the prompt -----
            chat_ready_done = asyncio.Event()
            engine_init_done = asyncio.Event()
            engine_init_exc: list[BaseException | None] = [None]

            # -- enter input loop ---------------------------------------------
            controller = None
            bootstrap_task = None
            diag(
                f'run() bootstrap_task created, events: chat_ready={chat_ready_done.is_set()}, engine_init={engine_init_done.is_set()}'
            )
            # RATE_LIMITED is intentionally omitted: the retry worker resumes the
            # agent after backoff; run_agent_until_done must keep running until a
            # true terminal state so controller.step() chains stay attached.
            end_states = [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
            ]

            self._hud.update_ledger('Starting')
            if session is not None:
                self._set_footer_system_line('Initializing engine...')
            else:
                renderer.add_system_message('Initializing engine...', title='system')
            bootstrap_task = asyncio.create_task(
                self._engine_bootstrap(
                    session,
                    renderer,
                    chat_ready_done,
                    engine_init_done,
                    engine_init_exc,
                ),
                name='grinta-engine-bootstrap',
            )

            iter_count = 0
            while self._running:
                iter_count += 1
                diag(f'run() iteration {iter_count} _running={self._running}')
                diag(
                    f'run() TOP OF LOOP iter={iter_count} _running={self._running} controller={"set" if controller else "None"} agent_task={"done" if agent_task and agent_task.done() else "pending" if agent_task else "None"}'
                )
                try:
                    stop = await self._repl_iteration(
                        session,
                        controller,
                        agent_task,
                        chat_ready_done,
                        engine_init_done,
                        engine_init_exc,
                        create_controller,
                        _create_early_status_callback,
                        run_agent_until_done,
                        end_states,
                    )
                except BaseException as exc:
                    logger.exception('Unhandled exception in REPL iteration')
                    import traceback

                    traceback.print_exc()
                    diag('run() caught BaseException, continuing')
                    try:
                        self._console.print(
                            f'[{CLR_STATUS_ERR}]Fatal error in REPL loop:[/] '
                            'see log or stderr for details.'
                        )
                    except Exception:
                        pass
                    # Continue looping so user can retry rather than silently
                    # terminating the session. Do NOT suppress SystemExit/KeyboardInterrupt
                    # — those still need to bubble up.
                    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                        raise
                    continue
                if stop is None:
                    diag(f'run() BREAKING at iter {iter_count}: stop is None')
                    break
                diag(
                    f'run() iter {iter_count} stop=({type(stop[0]).__name__ if stop[0] else "None"}, {type(stop[1]).__name__ if stop[1] else "None"})'
                )
                controller, agent_task = stop
        finally:
            diag('run() FINALLY block reached')
            await self._finalize_repl_run(bootstrap_task, agent_task)
            diag('run() EXIT')

    async def _repl_iteration(
        self,
        session: Any | None,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        chat_ready_done: asyncio.Event,
        engine_init_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None] | None:
        """Run one iteration of the REPL input loop. Returns None to break."""
        user_input = await self._read_repl_input(session)
        if user_input is None:
            return None
        if not user_input:
            return controller, agent_task
        text = user_input.strip()
        if not text or self._discard_terminal_noise(text):
            return controller, agent_task

        if text.startswith('/'):
            handled = await self._process_slash_command(
                text,
                agent_task,
                controller,
                engine_init_done,
                engine_init_exc,
                create_controller,
                create_status_callback,
                run_agent_until_done,
                end_states,
            )
            if handled is None:
                return None
            keep, controller, agent_task = handled
            if keep:
                return controller, agent_task
            # else fall through to dispatch (compact/retry)

        # Wait for engine to be fully initialized before dispatching.
        # Without this, validate below will fail and terminate the session.
        await engine_init_done.wait()
        await chat_ready_done.wait()
        if engine_init_exc[0] is not None:
            return controller, agent_task

        if not self._validate_engine_components_ready():
            return controller, agent_task

        controller, agent_task = await self._dispatch_user_turn(
            text,
            controller,
            agent_task,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
            session,
        )
        return controller, agent_task
