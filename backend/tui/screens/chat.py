"""Chat screen — main conversation workspace with streaming messages.

Improvements:
- Right sidebar (ActivityPanel) tracks files, thoughts, cost, steps.
- Inline diff hints on file edits.
- Agent changelog written to .forge/changelog.jsonl.
- Terminal bell fires on task completion.
- Playbook detection from observation events.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Select,
    Static,
)

from backend.tui.client import ForgeClient
from backend.tui.widgets.confirm_bar import ConfirmBar
from backend.tui.widgets.message_list import MessageList
from backend.tui.widgets.status_bar import AgentStatusBar
from backend.core.workspace_context import append_changelog, today_total_cost

logger = logging.getLogger("forge.tui.chat")

# Agent states that mean "waiting for user"
_AWAITING_STATES = frozenset({"awaiting_user_confirmation", "awaiting_user_input"})
_TERMINAL_STATES = frozenset({"stopped", "finished", "rejected", "error"})


class ChatScreen(Screen[None]):
    """Full-screen chat interface for a single conversation.

    Connects to the backend via Socket.IO and renders streaming events
    as they arrive.
    """

    BINDINGS = [
        Binding("ctrl+q", "go_home", "Back to Home", show=True),
        Binding("ctrl+d", "view_diff", "View Diff", show=True),
        Binding("ctrl+x", "stop_agent", "Stop Agent", show=True),
        Binding("escape", "dismiss_confirm", "Cancel", show=False),
    ]

    CSS = """
    #chat-outer {
        height: 100%;
    }
    #chat-main {
        width: 1fr;
        height: 100%;
    }
    #message-scroll {
        height: 1fr;
        padding: 0 1;
    }
    #input-row {
        height: 3;
        dock: bottom;
        padding: 0 1;
        border-top: hkey $primary;
    }
    #model-selector {
        width: 24;
        margin-right: 1;
    }
    #chat-input {
        width: 1fr;
    }
    .diff-hint {
        margin: 0 0 0 4;
        padding: 0 1;
        border-left: outer $primary;
        color: $text-muted;
    }
    .diff-add {
        color: $success;
    }
    .diff-del {
        color: $error;
    }
    """

    # Characters to show from old/new content in inline diff hints
    _DIFF_PREVIEW_CHARS = 100

    def __init__(self, client: ForgeClient, conversation_id: str) -> None:
        super().__init__()
        self.client = client
        self.conversation_id = conversation_id
        self._agent_state: str = "loading"
        self._pending_action: dict[str, Any] | None = None
        self._models_loaded: bool = False
        self._step_count: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="chat-outer"):
            with Vertical(id="chat-main"):
                yield VerticalScroll(
                    MessageList(id="message-list"), id="message-scroll"
                )
                yield ConfirmBar(id="confirm-bar")
                with Horizontal(id="input-row"):
                    yield Select[str](
                        [("Loading…", "__loading__")],
                        id="model-selector",
                        prompt="Model",
                        allow_blank=True,
                    )
                    yield Input(placeholder="Type a message…", id="chat-input")
        yield AgentStatusBar(id="agent-status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Connect to the conversation event stream."""
        self._add_system_message(
            f"Connecting to conversation {self.conversation_id[:8]}…"
        )
        try:
            await self._load_models()
            await self._apply_budget_limits()
            await self.client.join_conversation(
                self.conversation_id,
                on_event=self._handle_event,
            )
            self._add_system_message("Connected — streaming events")
        except Exception as e:
            self._add_system_message(f"Connection error: {e}")

    async def _apply_budget_limits(self) -> None:
        """Fetch budget limits from server and configure the status bar."""
        try:
            limits = await self.client.get_budget_limits()
            session_limit = limits.get("session_limit")
            daily_limit = limits.get("daily_limit")
            # Compute today's spend *before* this session from changelog
            daily_base = today_total_cost()
            status_bar = self.query_one("#agent-status-bar", AgentStatusBar)
            status_bar.set_limits(session_limit, daily_limit, daily_base)
        except Exception:
            pass  # Never block startup over budget config

    async def _load_models(self) -> None:
        """Populate the model selector from the backend."""
        try:
            models = await self.client.get_models()
            settings = await self.client.get_settings()
        except Exception as exc:
            logger.debug("Failed to load models/settings: %s", exc)
            return

        select = self.query_one("#model-selector", Select)
        options: list[tuple[str, str]] = []
        for m in models:
            model_id = str(m.get("id", m.get("model", str(m))))
            name = str(m.get("name", model_id))
            options.append((name, model_id))

        if not options:
            return

        select.set_options(options)

        # Determine the currently active model
        current_model = (
            settings.get("llm_model")
            or settings.get("llm", {}).get("model")
            or settings.get("model")
        )

        # Try to set it; fall back to first option
        self._models_loaded = True
        if current_model:
            valid_ids = {opt[1] for opt in options}
            if current_model in valid_ids:
                select.value = current_model
            else:
                select.value = options[0][1]
        else:
            select.value = options[0][1]

    async def on_unmount(self) -> None:
        """Clean up Socket.IO connection when leaving the screen."""
        try:
            await self.client.leave_conversation()
        except Exception:
            pass

    # ── input handling ────────────────────────────────────────────

    @on(Select.Changed, "#model-selector")
    async def _on_model_change(self, event: Select.Changed) -> None:
        # Skip programmatic changes and the loading placeholder
        if not self._models_loaded:
            return
        val = event.value
        if not val or val == Select.BLANK or val == "__loading__":
            return
        try:
            await self.client.save_settings({"llm_model": str(val)})
            self.notify(f"Switched to {val}")
        except Exception as e:
            self.notify(f"Failed to switch model: {e}", severity="error")

    @on(Input.Submitted, "#chat-input")
    async def _on_submit(self, event: Input.Submitted) -> None:
        content = event.value.strip()
        if not content:
            return
        event.input.value = ""
        self._add_user_message(content)
        try:
            await self.client.send_message(content)
        except Exception as e:
            self._add_system_message(f"Send failed: {e}")

    # ── confirmation bar events ───────────────────────────────────

    @on(ConfirmBar.Confirmed)
    async def _on_confirmed(self) -> None:
        await self.client.send_confirmation(confirm=True)
        self._hide_confirm_bar()

    @on(ConfirmBar.Rejected)
    async def _on_rejected(self) -> None:
        await self.client.send_confirmation(confirm=False)
        self._hide_confirm_bar()

    # ── event stream handler ──────────────────────────────────────

    async def _handle_event(self, data: dict[str, Any]) -> None:
        """Process a ``forge_event`` from the Socket.IO stream.

        python-socketio's async client runs callbacks *inside* the asyncio
        event loop but outside Textual's message pump.  We use
        ``call_from_thread`` which safely schedules processing on the
        Textual event loop regardless of the calling context.
        """
        try:
            self.app.call_from_thread(self._process_event, data)
        except Exception:
            # App might be shutting down; log and move on
            logger.debug("Event dispatch failed (app shutting down?)", exc_info=True)

    def _process_event(self, data: dict[str, Any]) -> None:
        """Dispatch event data to the appropriate widget update."""
        try:
            if "action" in data:
                self._handle_action(data)
            elif "observation" in data:
                self._handle_observation(data)
            elif "extras" in data and "agent_state" in data.get("extras", {}):
                new_state = data["extras"]["agent_state"]
                self._update_agent_state(new_state, data)

            llm_metrics = data.get("llm_metrics")
            if llm_metrics:
                status_bar = self.query_one("#agent-status-bar", AgentStatusBar)
                cost = llm_metrics.get("accumulated_cost")
                model = llm_metrics.get("model")
                if cost is not None:
                    status_bar.update_cost(cost)
                    append_changelog(
                        "cost_update",
                        {"cost": cost, "model": model or ""},
                        conversation_id=self.conversation_id,
                    )
                if model:
                    status_bar.update_model(model)
        except Exception:
            logger.debug("Error processing event", exc_info=True)

    # ── action events ─────────────────────────────────────────────

    def _handle_action(self, data: dict[str, Any]) -> None:
        action_type = data.get("action", "")
        args = data.get("args", {})

        if args.get("hidden"):
            return

        if action_type == "message":
            source = data.get("source", "")
            content = args.get("content", "")
            if source == "user":
                return
            self._add_assistant_message(content)
        elif action_type == "run":
            cmd = args.get("command", "")
            thought = args.get("thought", "")
            self._add_action_card("Run Command", cmd, thought)
            append_changelog(
                "command_run",
                {"command": cmd[:200]},
                conversation_id=self.conversation_id,
            )
        elif action_type == "read":
            path = args.get("path", "")
            self._add_action_card("Read File", path)
        elif action_type == "write":
            path = args.get("path", "")
            content = args.get("content", "")
            self._add_action_card("Write File", path)
            if content:
                first_line = next((ln for ln in content.splitlines() if ln.strip()), "")
                if first_line:
                    self._add_diff_hint(
                        f"+ {first_line[: self._DIFF_PREVIEW_CHARS]}",
                        css_class="diff-add",
                    )
            append_changelog(
                "file_write",
                {"path": path},
                conversation_id=self.conversation_id,
            )
        elif action_type == "edit":
            path = args.get("path", "")
            old_str = args.get("old_str", "")
            new_str = args.get("new_str", "")
            self._add_action_card("Edit File", path)
            self._show_inline_diff(old_str, new_str)
            append_changelog(
                "file_edit",
                {"path": path},
                conversation_id=self.conversation_id,
            )
        elif action_type == "browse":
            url = args.get("url", "")
            self._add_action_card("Browse", url)
            append_changelog(
                "browse",
                {"url": url[:300]},
                conversation_id=self.conversation_id,
            )
        elif action_type == "mcp":
            tool = args.get("tool_name", args.get("name", "mcp"))
            self._add_action_card(f"MCP: {tool}", str(args.get("arguments", "")))
        elif action_type == "think":
            thought = args.get("content", args.get("thought", ""))
            if thought:
                self._add_action_card("Thinking", thought)
        elif action_type in ("finish", "reject"):
            content = args.get("content", args.get("outputs", {}).get("content", ""))
            self._add_system_message(
                f"Agent {action_type}: {content}" if content else f"Agent {action_type}"
            )
            append_changelog(
                "task_finished" if action_type == "finish" else "task_rejected",
                {"message": content[:300] if content else ""},
                conversation_id=self.conversation_id,
            )
        else:
            self._add_action_card(action_type, str(args)[:200])

        # Increment step counter
        self._step_count += 1

        if "security_risk" in args:
            self._pending_action = data
            self._show_confirm_bar(action_type, args)

    def _show_inline_diff(self, old_str: str, new_str: str) -> None:
        """Show a compact before/after hint for file edits."""
        if not old_str and not new_str:
            return
        old_first = next((ln for ln in old_str.splitlines() if ln.strip()), "")
        new_first = next((ln for ln in new_str.splitlines() if ln.strip()), "")
        if old_first:
            self._add_diff_hint(
                f"- {old_first[: self._DIFF_PREVIEW_CHARS]}", css_class="diff-del"
            )
        if new_first:
            self._add_diff_hint(
                f"+ {new_first[: self._DIFF_PREVIEW_CHARS]}", css_class="diff-add"
            )

    # ── observation events ────────────────────────────────────────

    def _handle_observation(self, data: dict[str, Any]) -> None:
        obs_type = data.get("observation", "")
        content = data.get("content", "")
        extras = data.get("extras", {})

        if obs_type == "agent_state_changed":
            self._update_agent_state(extras.get("agent_state", ""), data)
            return
        if obs_type == "error":
            self._add_system_message(f"Error: {content}")
            append_changelog(
                "task_error",
                {"message": content[:300]},
                conversation_id=self.conversation_id,
            )
            return

        # Playbook knowledge — handled silently now or via messages
        if obs_type in ("playbook", "playbook_knowledge"):
            playbooks = extras.get("playbooks", [])
            if isinstance(playbooks, list) and playbooks:
                # Optionally notify user in chat
                self._add_system_message(f"Loaded playbooks: {', '.join(str(p) for p in playbooks)}")
            return

        msg_list = self.query_one("#message-list", MessageList)

        if obs_type == "run":
            display = content[:500] + "…" if len(content) > 500 else content
            msg_list.add_observation("Command Output", display)
        elif obs_type in ("read", "write", "edit"):
            msg = f"[{obs_type}] {content[:200]}" if content else f"[{obs_type}] done"
            msg_list.add_observation(obs_type.title(), msg)
        elif obs_type == "mcp":
            tool = extras.get("tool_name", "mcp")
            msg_list.add_observation(
                f"MCP: {tool}", content[:300] if content else "done"
            )
        elif obs_type in ("chat", "message"):
            self._add_assistant_message(content)
        elif content:
            msg_list.add_observation(obs_type or "observation", content[:300])

        self._scroll_to_bottom()

    # ── agent state ───────────────────────────────────────────────

    def _update_agent_state(self, new_state: str, data: dict[str, Any]) -> None:
        self._agent_state = new_state
        status_bar = self.query_one("#agent-status-bar", AgentStatusBar)
        status_bar.update_state(new_state)

        if new_state == "awaiting_user_confirmation":
            extras = data.get("extras", {})
            action_type = extras.get("confirmation_action_type", "action")
            self._show_confirm_bar(action_type, extras)
        elif new_state in ("running", "loading"):
            self._hide_confirm_bar()

        if new_state in _TERMINAL_STATES:
            self._add_system_message(f"Agent state: {new_state}")
            self._ring_bell()

    # ── widget helpers ────────────────────────────────────────────

    def _add_user_message(self, content: str) -> None:
        self.query_one("#message-list", MessageList).add_user_message(content)
        self._scroll_to_bottom()

    def _add_assistant_message(self, content: str) -> None:
        self.query_one("#message-list", MessageList).add_assistant_message(content)
        self._scroll_to_bottom()

    def _add_system_message(self, content: str) -> None:
        self.query_one("#message-list", MessageList).add_system_message(content)
        self._scroll_to_bottom()

    def _add_action_card(self, title: str, body: str, thought: str = "") -> None:
        self.query_one("#message-list", MessageList).add_action(title, body, thought)
        self._scroll_to_bottom()

    def _add_diff_hint(self, line: str, css_class: str = "") -> None:
        """Mount a compact inline diff hint below the last action card."""
        msg_list = self.query_one("#message-list", MessageList)
        classes = f"diff-hint {css_class}".strip()
        msg_list.mount(Static(line, classes=classes))
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scroll = self.query_one("#message-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def _show_confirm_bar(self, action_type: str, details: dict[str, Any]) -> None:
        bar = self.query_one("#confirm-bar", ConfirmBar)
        risk = details.get("security_risk")
        bar.show_confirmation(action_type, risk)

    def _hide_confirm_bar(self) -> None:
        self.query_one("#confirm-bar", ConfirmBar).hide_confirmation()

    def _ring_bell(self) -> None:
        """Emit a terminal bell to notify the user the task is done."""
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass

    # ── actions ───────────────────────────────────────────────────

    def action_go_home(self) -> None:
        self.dismiss()

    def action_view_diff(self) -> None:
        from backend.tui.screens.diff import DiffScreen

        self.app.push_screen(DiffScreen(self.client, self.conversation_id))

    async def action_stop_agent(self) -> None:
        try:
            await self.client.send_stop()
            self.notify("Stop requested")
        except Exception as e:
            self.notify(f"Stop failed: {e}", severity="error")

    def action_dismiss_confirm(self) -> None:
        self._hide_confirm_bar()
