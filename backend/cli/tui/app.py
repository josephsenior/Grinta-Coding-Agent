"""Grinta TUI — Textual Application screen and widgets.

Mission Control design — dolphie-inspired dashboard aesthetic.
Deep navy panels, teal accents, color-coded metrics, compact data-dense layout.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque

from pathlib import Path
from typing import Any

if os.getenv("DEBUG", "").strip().lower() not in ("true", "1", "yes"):
    os.environ["DEBUG"] = "1"

_tui_logger = logging.getLogger("grinta.tui")
_tui_logger.setLevel(logging.DEBUG)

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Label, RichLog, Static, TextArea

from backend.cli.config_manager import AppConfig
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import (
    NAVY_BORDER,
    NAVY_BRAND,
    NAVY_BRAND_DIM,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
    NAVY_TEXT_TERTIARY,
    NAVY_WAITING,
)
from backend.core.bootstrap.agent_control_loop import run_agent_until_done
from backend.core.bootstrap.main import (
    create_agent,
    create_registry_and_conversation_stats,
)
from backend.core.bootstrap.setup import create_memory, create_runtime
from backend.core.enums import AgentState, EventSource
from backend.core.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
from backend.ledger.action import (
    CmdRunAction,
    MessageAction,
    NullAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    CmdOutputObservation,
    NullObservation,
)
from backend.orchestration.conversation_stats import ConversationStats
from backend.orchestration.orchestration_config import OrchestrationConfig
from backend.orchestration.session_orchestrator import SessionOrchestrator
from backend.persistence import get_file_store

# ── Widget classes ────────────────────────────────────────────────────────


class TopBar(Static):
    """Compact 1-line top bar — 3-zone layout: title | workspace+model | help."""


class MetricsGrid(Horizontal):
    """Horizontal row of metric cards."""


class MetricsCard(Static):
    """Single metric card with title and value rows."""


class ReasoningPanel(Static):
    """Collapsible panel showing current action and streaming thoughts."""


class Transcript(VerticalScroll):
    """Scrollable conversation transcript."""


class InputBar(Horizontal):
    """Compact bottom input row."""


class FooterBar(Static):
    """1-line keyboard shortcuts footer."""


class GrintaConfirmDialog(ModalScreen[str | None]):
    """Confirmation dialog shown when the agent needs user input."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Cancel", show=False),
    ]

    def __init__(
        self,
        title: str,
        body: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        super().__init__()
        self._dialog_title = title
        self._dialog_body = body
        self._options = options
        self._recommended = recommended

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self._dialog_title}[/]", classes="title")
            yield Label(self._dialog_body, classes="body")
            for i, (key, label) in enumerate(self._options):
                yield Button(
                    label,
                    id=f"confirm-{key}",
                    variant="primary" if i == (self._recommended or 0) else "default",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for key, _label in self._options:
            if event.button.id == f"confirm-{key}":
                self.dismiss(key)
                return


# ── Main screen ───────────────────────────────────────────────────────────


class GrintaScreen(Screen):
    """Main TUI screen — Mission Control layout."""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "app.quit", "Quit", show=True, priority=True),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("ctrl+z", "suspend", "Suspend", show=False),
        Binding("enter", "submit_input", "Send", show=False, priority=True),
    ]

    def __init__(
        self,
        config: AppConfig,
        console: Any,
        loop: asyncio.AbstractEventLoop,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        app: App,
    ) -> None:
        super().__init__()
        self._config = config
        self._rich_console = console
        self._loop = loop
        self._hud = hud
        self._reasoning = reasoning
        self._main_app = app
        self._renderer: TUIRenderer | None = None
        self._event_stream: Any | None = None
        self._controller: Any | None = None
        self._agent_task: asyncio.Task[Any] | None = None
        self._runtime_stub: Any = None
        self._memory_stub: Any = None
        self._agent_running = True
        self._pending_confirm: asyncio.Event | None = None
        self._confirm_result: str | None = None
        self._input_lock = asyncio.Lock()

    _STATE_LABELS = {
        "starting": "Starting…",
        "loading": "Loading…",
        "running": "Running",
        "awaiting_user_input": "Ready",
        "paused": "Paused",
        "stopped": "Stopped",
        "finished": "Finished",
        "rejected": "Rejected",
        "error": "Error",
        "awaiting_user_confirmation": "Confirm",
        "user_confirmed": "Confirmed",
        "user_rejected": "Rejected",
        "rate_limited": "Rate Limited",
    }

    _STATE_COLORS = {
        "starting": NAVY_WAITING,
        "loading": NAVY_WAITING,
        "running": NAVY_BRAND,
        "awaiting_user_input": NAVY_READY,
        "paused": NAVY_WAITING,
        "stopped": NAVY_TEXT_MUTED,
        "finished": NAVY_READY,
        "rejected": NAVY_ERROR,
        "error": NAVY_ERROR,
        "awaiting_user_confirmation": NAVY_WAITING,
        "user_confirmed": NAVY_READY,
        "user_rejected": NAVY_ERROR,
        "rate_limited": NAVY_WAITING,
    }

    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")
        with MetricsGrid(id="metrics-grid"):
            yield MetricsCard(id="metrics-model", classes="metrics-card")
            yield MetricsCard(id="metrics-context", classes="metrics-card")
            yield MetricsCard(id="metrics-cost", classes="metrics-card")
            yield MetricsCard(id="metrics-status", classes="metrics-card")
        yield ReasoningPanel(id="reasoning-panel")
        with Transcript(id="transcript-scroll"):
            yield RichLog(id="transcript-log", markup=True, auto_scroll=True)
        with InputBar(id="input-bar"):
            yield Static("❯", id="input-prompt")
            yield TextArea(id="input")
        yield FooterBar(id="footer-bar")

    def on_mount(self) -> None:
        _tui_logger.debug("on_mount: GrintaScreen mounted")

        # Panelize the main layout sections
        transcript = self.query_one("#transcript-scroll", Transcript)
        transcript.border_title = "[#bbc8e8]Session Log[/]"

        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.border_title = "[#bbc8e8]Terminal[/]"

        self._render_topbar()
        self._render_metrics_grid()
        self._update_footer_bar()
        ta = self.query_one("#input", TextArea)
        ta.focus()
        ta.cursor_blink = True
        transcript.scroll_home(animate=False)
        _tui_logger.debug("on_mount: done")

    def on_unmount(self) -> None:
        _tui_logger.debug("on_unmount: GrintaScreen unmounting")
        if self._renderer:
            self._renderer._event_stream = None
        if self._event_stream is not None:
            try:
                close_fn = getattr(self._event_stream, "close", None)
                if callable(close_fn):
                    close_fn()
                    _tui_logger.debug("on_unmount: event_stream closed")
            except Exception as exc:
                _tui_logger.debug(f"on_unmount: event_stream close failed: {exc}")
        _tui_logger.debug("on_unmount: done")

    # ── TopBar ──────────────────────────────────────────────────────────────

    def _render_topbar(self) -> None:
        topbar = self.query_one("#top-bar", TopBar)
        hud = self._hud
        model = hud.state.model or "(not set)"
        workspace = hud.state.workspace_path or Path(os.getcwd()).name
        topbar.update(
            f"[{NAVY_BRAND}]Grinta[/]"
            f"  [{NAVY_TEXT_MUTED}]v3.0.7[/]"
            f"    [{NAVY_TEXT_SECONDARY}]{workspace}[/]"
            f"    [{NAVY_TEXT_MUTED}]{model}[/]"
            f"    [{NAVY_TEXT_DIM}]press ? for help[/]"
        )

    # ── MetricsGrid ─────────────────────────────────────────────────────────

    def _render_metrics_grid(self) -> None:
        self._update_model_card()
        self._update_context_card()
        self._update_cost_card()
        self._update_status_card()

    def _update_model_card(self) -> None:
        card = self.query_one("#metrics-model", MetricsCard)
        hud = self._hud
        provider, model = HUDBar.describe_model(hud.state.model)
        autonomy = hud.state.autonomy_level
        card.border_title = "[#bbc8e8]Model[/]"
        card.update(
            f"  [{NAVY_TEXT_PRIMARY}]{provider}[/]\n"
            f"  [{NAVY_TEXT_TERTIARY}]{model}[/]\n"
            f"  [{NAVY_TEXT_MUTED}]{autonomy}[/]"
        )

    def _update_context_card(self) -> None:
        card = self.query_one("#metrics-context", MetricsCard)
        hud = self._hud
        used = hud.state.context_tokens
        limit = hud.state.context_limit
        bar = self._render_context_bar(used, limit)
        condensations = hud.state.condensation_count
        card.border_title = "[#bbc8e8]Context[/]"
        card.update(
            f"  {bar}\n"
            f"  [{NAVY_TEXT_MUTED}]{used:,} / {limit:,} tokens[/]\n"
            f"  [{NAVY_TEXT_MUTED}]{condensations} condensations[/]"
        )

    def _render_context_bar(self, used: int, limit: int) -> str:
        if limit <= 0:
            return f"[{NAVY_TEXT_MUTED}]no limit[/]"
        pct = min(100, int(used / limit * 100))
        filled = int(pct / 10)
        empty = 10 - filled
        if pct < 70:
            color = "#54efae"  # green
        elif pct < 90:
            color = "#f6ff8f"  # yellow
        else:
            color = "#fd8383"  # red
        bar = f'[{color}]{"█" * filled}[/][{NAVY_BORDER}]{"░" * empty}[/]'
        return f"{bar}  [{color}]{pct}%[/]"

    def _update_cost_card(self) -> None:
        card = self.query_one("#metrics-cost", MetricsCard)
        hud = self._hud
        cost = hud.state.cost_usd
        calls = hud.state.llm_calls
        card.border_title = "[#bbc8e8]Cost[/]"
        card.update(
            f"  [{NAVY_TEXT_PRIMARY}]${cost:.4f}[/]\n"
            f"  [{NAVY_TEXT_TERTIARY}]{calls} LLM calls[/]"
        )

    def _update_status_card(self) -> None:
        card = self.query_one("#metrics-status", MetricsCard)
        hud = self._hud
        raw_state = hud.state.agent_state_label or "Ready"
        # Strip 'AgentState.' prefix if present for lookup
        lookup_key = raw_state.lower()
        if lookup_key.startswith("agentstate."):
            lookup_key = lookup_key[len("agentstate.") :]
        display_state = self._STATE_LABELS.get(lookup_key, raw_state)
        state_color = self._STATE_COLORS.get(lookup_key, NAVY_TEXT_MUTED)
        mcp = hud.state.mcp_servers
        mcp_str = f"{mcp} MCP" if mcp is not None else "— MCP"
        skills = HUDBar.count_bundled_playbook_skills()
        card.border_title = "[#bbc8e8]Status[/]"
        card.update(
            f"  [{state_color}]● {display_state}[/]\n"
            f"  [{NAVY_TEXT_TERTIARY}]{mcp_str}[/]\n"
            f"  [{NAVY_TEXT_MUTED}]{skills} skills[/]"
        )

    # ── ReasoningPanel ──────────────────────────────────────────────────────

    def _update_reasoning_panel(self) -> None:
        panel = self.query_one("#reasoning-panel", ReasoningPanel)
        if not self._reasoning.active:
            panel.remove_class("active")
            panel.update("")
            return
        panel.add_class("active")
        lines: list[str] = []
        if self._reasoning._current_action:
            lines.append(f"[{NAVY_BRAND_DIM}]▸ {self._reasoning._current_action}[/]")
        for thought in self._reasoning._committed_lines[-2:]:
            lines.append(f"  [{NAVY_TEXT_DIM}]{thought}[/]")
        if self._reasoning._streaming_line:
            lines.append(
                f"  [{NAVY_TEXT_TERTIARY}]{self._reasoning._streaming_line}[/]"
            )
        # Show ETA footer if available.
        eta = self._reasoning.eta_display
        if eta:
            elapsed = self._reasoning.elapsed_seconds
            elapsed_str = f"{elapsed}s" if elapsed is not None else "?"
            lines.append(
                f"  [{NAVY_TEXT_MUTED}]step {self._reasoning.step_count} · {elapsed_str} elapsed · {eta}[/]"
            )
        panel.update("\n".join(lines) if lines else "")

    # ── Transcript helpers ──────────────────────────────────────────────────

    def _get_log(self) -> RichLog:
        return self.query_one("#transcript-log", RichLog)

    def add_user_message(self, text: str) -> None:
        """User message — inline, color-coded prefix (dolphie style)."""
        self._get_log().write(f"[{NAVY_BRAND}]❯ you[/]  [{NAVY_TEXT_PRIMARY}]{text}[/]")
        # Clear reasoning panel and streaming dedup state for the new turn
        if self._renderer:
            self._renderer._streamed_final_text = None
            self._renderer._turn_active = True

    def add_agent_message(self, text: str) -> None:
        """Agent message — compact bordered panel."""
        self._get_log().write(
            f"[{NAVY_BRAND_DIM}]┌ grinta[/]\n"
            f"[{NAVY_TEXT_PRIMARY}]{text}[/]\n"
            f"[{NAVY_BRAND_DIM}]└[/]"
        )

    def add_system_message(self, text: str) -> None:
        self._get_log().write(f"[{NAVY_TEXT_MUTED}]{text}[/]")

    def add_error(self, text: str) -> None:
        self._get_log().write(f"[bold {NAVY_ERROR}]✗ {text}[/]")

    def add_success(self, text: str) -> None:
        self._get_log().write(f"[bold {NAVY_READY}]✓ {text}[/]")

    def add_tool_start(self, tool_name: str) -> None:
        """Tool call — indented with ▸ prefix."""
        self._get_log().write(
            f"  [{NAVY_BRAND_DIM}]▸[/]  [{NAVY_TEXT_TERTIARY}]{tool_name}[/]"
        )

    def add_tool_result(self, text: str) -> None:
        """Tool result — double-indented."""
        self._get_log().write(f"    [{NAVY_TEXT_MUTED}]{text}[/]")

    def add_divider(self) -> None:
        self._get_log().write(f"[{NAVY_BORDER}]" + "─" * 50 + "[/]")

    def clear_transcript(self) -> None:
        self._get_log().clear()

    def action_clear_transcript(self) -> None:
        self.clear_transcript()

    def action_suspend(self) -> None:
        self._agent_running = False
        self.app.exit()

    def _scroll_to_bottom(self) -> None:
        self.query_one("#transcript-scroll", Transcript).scroll_end(animate=False)

    # ── FooterBar ───────────────────────────────────────────────────────────

    def _update_footer_bar(self) -> None:
        self.query_one("#footer-bar", FooterBar).update(
            f"[{NAVY_TEXT_MUTED}]"
            f"[^C] Quit   "
            f"[^L] Clear   "
            f"[Enter] Send"
            f"[/]"
        )

    # ── Input handling ──────────────────────────────────────────────────────

    def action_submit_input(self) -> None:
        _tui_logger.debug(f"action_submit_input: lock_locked={self._input_lock.locked()}")
        if self._input_lock.locked():
            _tui_logger.debug("action_submit_input: lock held, ignoring")
            return
        ta = self.query_one("#input", TextArea)
        text = ta.text.strip()
        _tui_logger.debug(f"action_submit_input: text_len={len(text)}")
        if not text:
            _tui_logger.debug("action_submit_input: empty text, ignoring")
            return
        _tui_logger.debug(f"action_submit_input: creating task for _handle_input")
        try:
            task = asyncio.create_task(self._handle_input(text))
            _tui_logger.debug(f"action_submit_input: task created {task}")

            def _on_done(t: asyncio.Task[Any]) -> None:
                exc = t.exception()
                if exc:
                    _tui_logger.debug(f"_handle_input task FAILED: {type(exc).__name__}: {exc}")
                else:
                    _tui_logger.debug(f"_handle_input task completed OK")

            task.add_done_callback(_on_done)
        except Exception as exc:
            _tui_logger.debug(
                f"action_submit_input: create_task FAILED: {type(exc).__name__}: {exc}"
            )

    async def _handle_input(self, text: str) -> None:
        try:
            _tui_logger.debug(f"_handle_input ENTER text={text[:80]}")
        except Exception as exc:
            _tui_logger.debug(f"_handle_input: _trace FAILED: {type(exc).__name__}: {exc}")
        async with self._input_lock:
            ta = self.query_one("#input", TextArea)
            ta.clear()
            ta.focus()
            self._scroll_to_bottom()

            if text.startswith("/"):
                await self._handle_slash_command(text)
                return

            self.add_user_message(text)
            self._update_footer_bar()
            self.query_one("#input-bar", InputBar).add_class("processing")

            try:
                _tui_logger.debug(f"_handle_input: controller={self._controller is not None}")
                if self._controller is None:
                    _tui_logger.debug("_handle_input: calling _bootstrap()")
                    logger.info("[TUI] _handle_input: bootstrapping (no controller)")
                    self.add_system_message(f"[{NAVY_BRAND}]Bootstrapping engine…[/]")
                    await self._bootstrap()
                    if self._controller is None:
                        raise RuntimeError("Bootstrap failed to initialize controller")
                    _tui_logger.debug(
                        f"_handle_input: _bootstrap done, state={self._controller.get_agent_state()}"
                    )
                    logger.info(
                        "[TUI] _handle_input: bootstrap complete, state=%s",
                        self._controller.get_agent_state(),
                    )
                    self.add_system_message(
                        f"[{NAVY_READY}]Engine ready — dispatching task[/]"
                    )
                else:
                    _tui_logger.debug(
                        "_handle_input: controller exists, calling _ensure_agent_task()"
                    )
                    logger.info("[TUI] _handle_input: controller exists, ensuring task")
                    await self._ensure_agent_task()
                assert self._controller is not None, "Controller must be initialized after agent task setup"
                _tui_logger.debug("_handle_input: calling _dispatch_to_agent()")
                logger.info("[TUI] _handle_input: dispatching to agent")
                await self._dispatch_to_agent(text)
                _tui_logger.debug(
                    f"_handle_input: _dispatch_to_agent done, state={self._controller.get_agent_state()}"
                )
                logger.info(
                    "[TUI] _handle_input: dispatch complete, state=%s",
                    self._controller.get_agent_state() if self._controller else "N/A",
                )
            except Exception:
                _tui_logger.debug("_handle_input: EXCEPTION in try block")
                logger.exception("[TUI] _handle_input FAILED")
                self.add_error("Agent error — check app.log")
                self._update_footer_bar()
                if self._controller:
                    try:
                        actual = str(self._controller.get_agent_state())
                        self._hud.update_agent_state(actual or "Error")
                        self._render_topbar()
                        self._render_metrics_grid()
                    except Exception:
                        self._hud.update_agent_state("Error")
                        self._render_topbar()
                        self._render_metrics_grid()
            finally:
                self._update_footer_bar()
                self.query_one("#input-bar", InputBar).remove_class("processing")
                if self._renderer:
                    self._renderer.drain_events()
                state_label = self._hud.state.agent_state_label or "Ready"
                logger.info("[TUI] _handle_input: finally, HUD state=%r", state_label)
                self._hud.update_agent_state(state_label)
                self._render_topbar()
                self._render_metrics_grid()

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or "Ready")
        self._render_topbar()
        self._render_metrics_grid()

    async def _handle_slash_command(self, text: str) -> None:
        cmd = text.lower().strip()
        if cmd in ("/help", "/h", "/?"):
            self.show_help()
        elif cmd in ("/clear", "/c"):
            self.clear_transcript()
        elif cmd in ("/quit", "/q", "/exit"):
            self._agent_running = False
            self.app.exit()
        elif cmd == "/settings":
            self.add_system_message("/settings opens settings TUI (coming soon)")
        elif cmd == "/sessions":
            self.add_system_message("/sessions opens sessions manager (coming soon)")
        else:
            self.add_error(f"Unknown command: {text}")

    def show_help(self) -> None:
        self.add_divider()
        self.add_system_message(
            f"[{NAVY_BRAND}]GRINTA[/] — AI-Powered Development Platform"
        )
        self.add_divider()
        self._get_log().write(
            f"  [{NAVY_TEXT_SECONDARY}]/help[/]      [{NAVY_TEXT_TERTIARY}]Show this help[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]/clear[/]     [{NAVY_TEXT_TERTIARY}]Clear transcript[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]/settings[/]  [{NAVY_TEXT_TERTIARY}]Open settings[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]/sessions[/]  [{NAVY_TEXT_TERTIARY}]Manage sessions[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]/quit[/]      [{NAVY_TEXT_TERTIARY}]Exit Grinta[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]Ctrl+C[/]     [{NAVY_TEXT_TERTIARY}]Stop agent[/]\n"
            f"  [{NAVY_TEXT_SECONDARY}]Tab[/]        [{NAVY_TEXT_TERTIARY}]Newline in input[/]"
        )
        self.add_divider()
        self._scroll_to_bottom()

    # ── Bootstrap (preserved agent logic) ───────────────────────────────────

    async def _bootstrap(self) -> None:
        _tui_logger.debug("_bootstrap: start")
        logger.info("TUI _bootstrap: starting")
        self._hud.update_agent_state("Initializing")
        self._render_topbar()
        self._render_metrics_grid()
        self.add_system_message(f"[{NAVY_BRAND}]Initializing engine…[/]")

        config = self._config

        try:
            agent, event_stream, runtime = await asyncio.to_thread(
                self._bootstrap_sync_phase1, config
            )
        except Exception as exc:
            _tui_logger.debug(f"_bootstrap: EXCEPTION phase1 {type(exc).__name__}: {exc}")
            logger.exception("TUI _bootstrap: failed in phase1")
            raise

        _tui_logger.debug(f"_bootstrap: runtime created, type={type(runtime).__name__}")

        connect_fn = getattr(runtime, "connect", None)
        if callable(connect_fn):
            try:
                _tui_logger.debug("_bootstrap: awaiting runtime.connect()")
                await connect_fn()
                _tui_logger.debug("_bootstrap: runtime.connect() OK")
            except Exception as exc:
                _tui_logger.debug(
                    f"_bootstrap: runtime.connect() FAILED: {type(exc).__name__}: {exc}"
                )
                raise

        try:
            memory, controller = await asyncio.to_thread(
                self._bootstrap_sync_phase2, agent, runtime, event_stream, config
            )
        except Exception as exc:
            _tui_logger.debug(f"_bootstrap: EXCEPTION phase2 {type(exc).__name__}: {exc}")
            logger.exception("TUI _bootstrap: failed in phase2")
            raise

        _tui_logger.debug(f"_bootstrap: controller created, state={controller.get_agent_state()}")
        logger.info(
            "TUI _bootstrap: controller created, initial state=%s (type=%s)",
            controller.get_agent_state(),
            type(controller.get_agent_state()),
        )

        self._event_stream = event_stream
        self._runtime_stub = runtime
        self._memory_stub = memory
        self._controller = controller

        from backend.utils.async_utils import set_main_event_loop

        set_main_event_loop(self._loop)
        _tui_logger.debug(f"_bootstrap: set_main_event_loop to {self._loop}")

        if self._renderer is None:
            self._renderer = TUIRenderer(
                console=self._rich_console,
                hud=self._hud,
                reasoning=self._reasoning,
                tui=self,
                loop=self._loop,
            )
        self._renderer.subscribe(event_stream, event_stream.sid)

        state_after_create = controller.get_agent_state()
        _tui_logger.debug(f"_bootstrap: state after subscribe={state_after_create}")
        logger.info(
            "TUI _bootstrap: state after renderer subscribe=%s", state_after_create
        )
        self._hud.update_agent_state(str(state_after_create))
        self._render_topbar()
        self._render_metrics_grid()
        self._renderer.drain_events()
        _tui_logger.debug("_bootstrap: done")
        self.add_system_message(f"[{NAVY_READY}]Engine ready.[/]")

    def _bootstrap_sync_phase1(
        self,
        config: Any,
    ) -> tuple[Any, Any, Any]:
        _tui_logger.debug("_bootstrap_sync_phase1: get_file_store")
        file_store = get_file_store(config)
        _tui_logger.debug("_bootstrap_sync_phase1: EventStream")
        event_stream = EventStream(sid="grinta-tui", file_store=file_store)
        _tui_logger.debug("_bootstrap_sync_phase1: create_registry_and_conversation_stats")
        llm_registry, _conv_stats, _app_cfg = create_registry_and_conversation_stats(
            config,
            sid=event_stream.sid,
            user_id="tui",
        )
        _tui_logger.debug("_bootstrap_sync_phase1: create_runtime")
        runtime = create_runtime(
            config,
            llm_registry=llm_registry,
            sid=event_stream.sid,
            event_stream=event_stream,
        )
        _tui_logger.debug("_bootstrap_sync_phase1: create_agent")
        agent = create_agent(config, llm_registry)
        _tui_logger.debug("_bootstrap_sync_phase1: done")
        return agent, event_stream, runtime

    def _bootstrap_sync_phase2(
        self,
        agent: Any,
        runtime: Any,
        event_stream: Any,
        config: Any,
    ) -> tuple[Any, Any]:
        _tui_logger.debug("_bootstrap_sync_phase2: create_memory")
        memory = create_memory(runtime, event_stream, sid=event_stream.sid)
        _tui_logger.debug("_bootstrap_sync_phase2: create_memory done")
        _tui_logger.debug("_bootstrap_sync_phase2: controller")
        controller = self._get_or_create_controller(
            agent,
            runtime,
            memory,
            event_stream,
            config,
        )
        _tui_logger.debug("_bootstrap_sync_phase2: controller done")
        return memory, controller

    def _get_or_create_controller(
        self,
        agent: Any,
        runtime: Any,
        memory: Any,
        event_stream: Any,
        config: Any,
    ) -> Any:
        return SessionOrchestrator(
            config=OrchestrationConfig(
                agent=agent,
                event_stream=event_stream,
                conversation_stats=ConversationStats(
                    file_store=event_stream.file_store,
                    conversation_id=event_stream.sid,
                    user_id=None,
                ),
                iteration_delta=config.max_iterations,
                headless_mode=True,
            )
        )

    async def _run_agent_loop(self) -> None:
        if self._controller is None:
            _tui_logger.debug("_run_agent_loop: no controller, aborting")
            return
        _tui_logger.debug("_run_agent_loop: ENTER")
        end_states = [
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ]
        try:
            _tui_logger.debug("_run_agent_loop: calling run_agent_until_done")
            await run_agent_until_done(
                self._controller,
                self._runtime_stub,
                self._memory_stub,
                end_states,
            )
            _tui_logger.debug("_run_agent_loop: run_agent_until_done returned")
        except Exception as exc:
            _tui_logger.debug(f"_run_agent_loop: EXCEPTION {type(exc).__name__}: {exc}")
            logger.exception("Agent loop exited with error")
        _tui_logger.debug("_run_agent_loop: EXIT")

    async def _ensure_agent_task(self) -> None:
        if self._controller is None:
            _tui_logger.debug("_ensure_agent_task: no controller, returning")
            return

        state = self._controller.get_agent_state()
        _tui_logger.debug(f"_ensure_agent_task: current state={state}")
        logger.info("TUI _ensure_agent_task: current state=%s", state)
        if state in {
            AgentState.LOADING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            _tui_logger.debug(f"_ensure_agent_task: transitioning {state} -> RUNNING")
            logger.info("TUI _ensure_agent_task: transitioning %s -> RUNNING", state)
            await self._controller.set_agent_state_to(AgentState.RUNNING)
        elif state == AgentState.RUNNING:
            _tui_logger.debug("_ensure_agent_task: already RUNNING")
            logger.info("TUI _ensure_agent_task: already RUNNING")

        state_after = self._controller.get_agent_state()
        _tui_logger.debug(f"_ensure_agent_task: state after transition={state_after}")
        logger.info("TUI _ensure_agent_task: state after transition=%s", state_after)

        if self._agent_task is None or self._agent_task.done():
            _tui_logger.debug("_ensure_agent_task: creating new agent task")
            logger.info("TUI _ensure_agent_task: creating new agent task")
            self._agent_task = asyncio.create_task(
                run_agent_until_done(
                    self._controller,
                    self._runtime_stub,
                    self._memory_stub,
                    [
                        AgentState.AWAITING_USER_INPUT,
                        AgentState.FINISHED,
                        AgentState.ERROR,
                        AgentState.STOPPED,
                    ],
                ),
                name="grinta-tui-agent",
            )

            def _on_agent_done(t: asyncio.Task[Any]) -> None:
                exc = t.exception()
                if exc:
                    _tui_logger.debug(f"_agent_task FAILED: {type(exc).__name__}: {exc}")
                    logger.exception("TUI _agent_task failed")
                else:
                    _tui_logger.debug("_agent_task completed OK")

            self._agent_task.add_done_callback(_on_agent_done)
        else:
            _tui_logger.debug(
                f"_ensure_agent_task: agent task already running task={self._agent_task}"
            )
            logger.info(
                "TUI _ensure_agent_task: agent task already running (task=%s)",
                self._agent_task,
            )

    async def _dispatch_to_agent(self, text: str) -> None:
        _tui_logger.debug("_dispatch_to_agent: ENTER")
        if self._controller is None or self._event_stream is None:
            _tui_logger.debug("_dispatch_to_agent: missing controller or event_stream, returning")
            return

        try:
            await self._ensure_agent_task()
            _tui_logger.debug("_dispatch_to_agent: _ensure_agent_task OK")
        except Exception as exc:
            _tui_logger.debug(
                f"_dispatch_to_agent: _ensure_agent_task FAILED: {type(exc).__name__}: {exc}"
            )
            raise

        action = MessageAction(content=text)
        self._event_stream.add_event(action, EventSource.USER)
        # NOTE: _ensure_agent_task (via run_agent_until_done) already calls
        # controller.step() internally.  We skip the redundant explicit step()
        # to avoid double-processing the queued MessageAction.
        _tui_logger.debug("_dispatch_to_agent: event added")
        try:
            logger.info("[TUI] _dispatch_to_agent: event added")
        except Exception as exc:
            _tui_logger.debug(
                f"_dispatch_to_agent: logger.info FAILED: {type(exc).__name__}: {exc}"
            )
        try:
            end_states = {
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.AWAITING_USER_CONFIRMATION,
            }
            _tui_logger.debug("_dispatch_to_agent: end_states created")
        except Exception as exc:
            _tui_logger.debug(
                f"_dispatch_to_agent: end_states FAILED: {type(exc).__name__}: {exc}"
            )
            raise
        loop_count = 0
        import time as _time

        _poll_started = _time.monotonic()
        _max_poll_seconds = 600  # 10-minute hard cap for the polling loop
        _tui_logger.debug("_dispatch_to_agent: entering poll loop")
        while True:
            try:
                await asyncio.sleep(0.1)
                loop_count += 1
                state = self._controller.get_agent_state()
                if loop_count == 1 or loop_count % 20 == 0:
                    _tui_logger.debug(f"_dispatch_to_agent: poll #{loop_count}, state={state}")
                    logger.info(
                        "[TUI] _dispatch_to_agent: poll #%d, state=%s",
                        loop_count,
                        state,
                    )
                if state in end_states:
                    _tui_logger.debug(f"_dispatch_to_agent: reached end state {state}")
                    logger.info("[TUI] _dispatch_to_agent: reached end state %s", state)
                    break
                if self._agent_task and self._agent_task.done():
                    _tui_logger.debug(f"_dispatch_to_agent: agent task done, state={state}")
                    logger.info(
                        "[TUI] _dispatch_to_agent: agent task done, state=%s", state
                    )
                    break
                if self._renderer:
                    self._renderer.drain_events()
                # Hard timeout: prevent infinite polling if the agent gets stuck.
                if _time.monotonic() - _poll_started > _max_poll_seconds:
                    _tui_logger.debug("_dispatch_to_agent: poll timeout reached")
                    logger.error(
                        "[TUI] _dispatch_to_agent: poll timeout after %.0fs in state=%s",
                        _max_poll_seconds,
                        state,
                    )
                    self.add_error("Agent timed out — check app.log")
                    break
            except Exception as exc:
                _tui_logger.debug(
                    f"_dispatch_to_agent: poll loop EXCEPTION {type(exc).__name__}: {exc}"
                )
                raise
        _tui_logger.debug("_dispatch_to_agent: poll loop exited")

    # ── Confirmation ────────────────────────────────────────────────────────

    async def confirm(
        self,
        title: str,
        body: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> str | None:
        dialog = GrintaConfirmDialog(title, body, options, recommended)
        result = await self.app.push_screen_wait(dialog)
        return result


# ── TUIRenderer ───────────────────────────────────────────────────────────


class TUIRenderer:
    """Textual renderer — subscribes to event stream and updates TUI widgets."""

    def __init__(
        self,
        console: Any,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        tui: GrintaScreen,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._tui = tui
        self._loop = loop
        self._event_stream: Any | None = None
        self._state_event = asyncio.Event()
        self._current_state: Any = None
        self._pending_events: deque[Any] = deque()
        self._pending_lock = threading.Lock()
        # Track the last message rendered via streaming final chunk —
        # used to suppress duplicate MessageAction from the backend.
        self._streamed_final_text: str | None = None
        # Tracks whether the current turn is complete to prevent cross-turn leak.
        self._turn_active: bool = False

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(EventStreamSubscriber.MAIN, self._on_event, sid)

    def drain_events(self) -> None:
        if not self._pending_events:
            return
        _tui_logger.debug(f"TUIRenderer.drain_events: {len(self._pending_events)} pending")
        with self._pending_lock:
            while self._pending_events:
                event = self._pending_events.popleft()
        self._process_event(event)

    def _on_event(self, event: Any) -> None:
        _tui_logger.debug(f"TUIRenderer._on_event: {type(event).__name__}")
        with self._pending_lock:
            self._pending_events.append(event)
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def wait_for_state_change(self, wait_timeout_sec: float = 0.1) -> asyncio.Event:
        self._state_event.clear()
        return self._state_event

    def _process_event(self, event: Any) -> None:
        _tui_logger.debug(
            f'TUIRenderer._process_event: {type(event).__name__} source={getattr(event, "source", None)}'
        )
        self._update_metrics(event)

        if isinstance(event, NullAction) or isinstance(event, NullObservation):
            return

        source = getattr(event, "source", None)

        if isinstance(event, MessageAction) and source == EventSource.AGENT:
            content = event.content or ""
            # Skip if this MessageAction duplicates a message already rendered
            # by the final StreamingChunkAction for this turn.
            if content and content == self._streamed_final_text:
                self._streamed_final_text = None
                return
            if content:
                self._tui.add_agent_message(content)
        elif isinstance(event, CmdRunAction) and source == EventSource.AGENT:
            cmd = getattr(event, "command", "") or ""
            self._tui.add_tool_start(cmd[:80])
        elif isinstance(event, CmdOutputObservation):
            output = (event.content or "").strip()
            if output:
                self._tui.add_tool_result(output[:500])
        elif isinstance(event, StreamingChunkAction):
            self._handle_streaming_chunk(event)
        elif isinstance(event, AgentStateChangedObservation):
            self._handle_state_change(event)

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        """Handle streaming chunk — update reasoning in real-time, transcript only on final."""
        # Real-time thinking/reasoning tokens
        thinking = (action.thinking_accumulated or "").strip()
        if thinking:
            self._reasoning.start()
            self._reasoning.set_streaming_thought(thinking)
            self._tui._update_reasoning_panel()
            self._state_event.set()

        # Tool call streaming: show in reasoning display
        if action.is_tool_call:
            tool_name = action.tool_call_name or "tool"
            self._reasoning.start()
            self._reasoning.update_action(f"{tool_name}…")
            self._tui._update_reasoning_panel()
            self._state_event.set()
            return

        # Live cost update during streaming
        # NOTE: _update_metrics (called for every event) already accumulates cost
        # via event.cost_usd.  We skip adding cost here to avoid double-counting.

        # Only add to transcript when streaming is complete
        if action.is_final:
            text = (action.accumulated or "").strip()
            if text:
                self._streamed_final_text = text
                self._tui.add_agent_message(text)
            self._reasoning.stop()
            self._tui._update_reasoning_panel()
            self._tui._render_metrics_grid()

    def _update_metrics(self, event: Any) -> None:
        if hasattr(event, "model") and event.model:
            self._hud.update_model(event.model)
        if hasattr(event, "llm_metrics") and event.llm_metrics:
            self._hud.update_from_llm_metrics(event.llm_metrics)
        cost = getattr(event, "cost_usd", None)
        if cost is not None and cost > 0:
            self._hud.update_cost(self._hud.state.cost_usd + cost)

    def _handle_state_change(self, obs: Any) -> None:
        state = obs.agent_state
        try:
            state = AgentState(state)
        except (ValueError, TypeError):
            pass

        self._current_state = state
        self._hud.update_agent_state(str(state))
        self._state_event.set()
        # Direct calls since _handle_state_change runs on the main loop
        # (called from _process_event which is called from drain_events on the
        # main thread).  No need for call_soon_threadsafe.
        self._tui._render_topbar()
        self._tui._render_metrics_grid()

        # Clear reasoning panel when agent becomes idle
        if state in {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        }:
            self._reasoning.stop()
            self._tui._update_reasoning_panel()
            # Reset streaming dedup state at turn boundary.
            self._streamed_final_text = None
            self._turn_active = False
