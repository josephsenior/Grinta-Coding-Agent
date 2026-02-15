"""Chat screen — main conversation workspace with streaming messages."""

from __future__ import annotations

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
)

from backend.tui.client import ForgeClient
from backend.tui.widgets.confirm_bar import ConfirmBar
from backend.tui.widgets.message_list import MessageList
from backend.tui.widgets.status_bar import AgentStatusBar

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
    #chat-input {
        width: 1fr;
    }
    """

    def __init__(self, client: ForgeClient, conversation_id: str) -> None:
        super().__init__()
        self.client = client
        self.conversation_id = conversation_id
        self._agent_state: str = "loading"
        self._pending_action: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="chat-outer"):
            yield VerticalScroll(MessageList(id="message-list"), id="message-scroll")
            yield ConfirmBar(id="confirm-bar")
            with Horizontal(id="input-row"):
                yield Input(placeholder="Type a message…", id="chat-input")
        yield AgentStatusBar(id="agent-status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Connect to the conversation event stream."""
        self._add_system_message(
            f"Connecting to conversation {self.conversation_id[:8]}…"
        )
        try:
            await self.client.join_conversation(
                self.conversation_id,
                on_event=self._handle_event,
            )
            self._add_system_message("Connected — streaming events")
        except Exception as e:
            self._add_system_message(f"Connection error: {e}")

    async def on_unmount(self) -> None:
        """Clean up Socket.IO connection when leaving the screen."""
        await self.client.leave_conversation()

    # ── input handling ────────────────────────────────────────────

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
        """Process a single ``forge_event`` from the Socket.IO stream.

        This is called from the Socket.IO reader task inside python-socketio,
        so we need to use ``call_from_thread`` / ``post_message`` to update
        the Textual widget tree safely.
        """
        # Delegate to the UI thread
        self.app.call_from_thread(self._process_event, data)

    def _process_event(self, data: dict[str, Any]) -> None:
        """Dispatch event data to the appropriate widget update."""
        if "action" in data:
            self._handle_action(data)
        elif "observation" in data:
            self._handle_observation(data)
        elif "extras" in data and "agent_state" in data.get("extras", {}):
            new_state = data["extras"]["agent_state"]
            self._update_agent_state(new_state, data)

        # Update metrics if present
        llm_metrics = data.get("llm_metrics")
        if llm_metrics:
            status_bar = self.query_one("#agent-status-bar", AgentStatusBar)
            cost = llm_metrics.get("accumulated_cost")
            model = llm_metrics.get("model")
            if cost is not None:
                status_bar.update_cost(cost)
            if model:
                status_bar.update_model(model)

    # ── action events ─────────────────────────────────────────────

    def _handle_action(self, data: dict[str, Any]) -> None:
        action_type = data.get("action", "")
        args = data.get("args", {})

        # Hidden actions are internal — skip
        if args.get("hidden"):
            return

        if action_type == "message":
            # Agent message (not user — user messages come via our input)
            source = data.get("source", "")
            content = args.get("content", "")
            if source == "user":
                # Already shown via _add_user_message, skip duplicate
                return
            self._add_assistant_message(content)

        elif action_type == "run":
            # Command execution
            cmd = args.get("command", "")
            thought = args.get("thought", "")
            self._add_action_card("Run Command", cmd, thought)

        elif action_type == "read":
            path = args.get("path", "")
            self._add_action_card("Read File", path)

        elif action_type == "write":
            path = args.get("path", "")
            self._add_action_card("Write File", path)

        elif action_type == "edit":
            path = args.get("path", "")
            self._add_action_card("Edit File", path)

        elif action_type == "browse":
            url = args.get("url", "")
            self._add_action_card("Browse", url)

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

        else:
            # Generic action
            self._add_action_card(action_type, str(args)[:200])

        # If the action has security_risk, show confirmation
        if "security_risk" in args:
            self._pending_action = data
            self._show_confirm_bar(action_type, args)

    # ── observation events ────────────────────────────────────────

    def _handle_observation(self, data: dict[str, Any]) -> None:
        obs_type = data.get("observation", "")
        content = data.get("content", "")
        extras = data.get("extras", {})

        if obs_type == "agent_state_changed":
            new_state = extras.get("agent_state", "")
            self._update_agent_state(new_state, data)
            return

        if obs_type == "error":
            self._add_system_message(f"Error: {content}")
            return

        if obs_type == "run":
            # Truncate long command output for display
            display_content = content[:500] + "…" if len(content) > 500 else content
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.add_observation("Command Output", display_content)
            return

        if obs_type in ("read", "write", "edit"):
            msg = f"[{obs_type}] {content[:200]}" if content else f"[{obs_type}] done"
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.add_observation(obs_type.title(), msg)
            return

        if obs_type == "mcp":
            tool = extras.get("tool_name", "mcp")
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.add_observation(
                f"MCP: {tool}", content[:300] if content else "done"
            )
            return

        if obs_type in ("chat", "message"):
            self._add_assistant_message(content)
            return

        # Generic observation
        if content:
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.add_observation(obs_type or "observation", content[:300])

    # ── agent state ───────────────────────────────────────────────

    def _update_agent_state(self, new_state: str, data: dict[str, Any]) -> None:
        self._agent_state = new_state
        status_bar = self.query_one("#agent-status-bar", AgentStatusBar)
        status_bar.update_state(new_state)

        if new_state == "awaiting_user_confirmation":
            # Show the confirmation bar
            extras = data.get("extras", {})
            action_type = extras.get("confirmation_action_type", "action")
            self._show_confirm_bar(action_type, extras)
        elif new_state in ("running", "loading"):
            self._hide_confirm_bar()

        if new_state in _TERMINAL_STATES:
            self._add_system_message(f"Agent state: {new_state}")

    # ── widget helpers ────────────────────────────────────────────

    def _add_user_message(self, content: str) -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.add_user_message(content)
        self._scroll_to_bottom()

    def _add_assistant_message(self, content: str) -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.add_assistant_message(content)
        self._scroll_to_bottom()

    def _add_system_message(self, content: str) -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.add_system_message(content)
        self._scroll_to_bottom()

    def _add_action_card(self, title: str, body: str, thought: str = "") -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.add_action(title, body, thought)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        scroll = self.query_one("#message-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def _show_confirm_bar(self, action_type: str, details: dict[str, Any]) -> None:
        bar = self.query_one("#confirm-bar", ConfirmBar)
        risk = details.get("security_risk")
        bar.show_confirmation(action_type, risk)

    def _hide_confirm_bar(self) -> None:
        bar = self.query_one("#confirm-bar", ConfirmBar)
        bar.hide_confirmation()

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
