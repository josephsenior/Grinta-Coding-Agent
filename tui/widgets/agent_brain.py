"""Agent Brain sidebar — shows what the LLM is actively doing.

Displays:
- Current State (Thinking, Executing, Observing, etc.)
- Repetition Score / Stuck Warning (heat gauge)
- Recent Tool Calls (scrolling list)
- Memory Pressure (proximity to condensation)
- Files touched, thoughts, playbooks (from ActivityPanel)
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import ProgressBar, Static

# Map agent states to display labels
_STATE_LABELS: dict[str, str] = {
    "loading": "Loading",
    "running": "Running",
    "thinking": "Thinking",
    "executing": "Executing",
    "observing": "Observing",
    "validating": "Validating",
    "condensed": "Condensed",
    "awaiting_user_input": "Awaiting Input",
    "awaiting_user_confirmation": "Needs Confirm",
    "paused": "Paused",
    "stopped": "Stopped",
    "finished": "Finished",
    "rejected": "Rejected",
    "error": "Error",
    "rate_limited": "Rate Limited",
}


class AgentBrain(Widget):
    """Right sidebar: agent state, repetition score, tool calls, memory pressure."""

    DEFAULT_CSS = """
    AgentBrain {
        width: 32;
        min-width: 28;
        max-width: 40;
        border-left: vkey #1a1a1a;
        padding: 0 1;
        background: #0a0a0a;
        overflow-y: auto;
    }
    .ab-heading {
        text-style: bold;
        color: $accent;
        margin: 1 0 0 0;
    }
    .ab-state {
        color: $primary;
        text-style: bold;
        margin: 0 0 1 0;
    }
    .ab-state.stuck-warning {
        color: $error;
    }
    .ab-divider {
        color: $primary-darken-1;
    }
    .ab-tools {
        color: $text;
        margin: 0 0 1 0;
        height: auto;
        max-height: 12;
    }
    .ab-tool-item {
        padding: 0 0 0 1;
        color: $text-muted;
    }
    .ab-files {
        color: $text;
        margin: 0 0 1 0;
    }
    .ab-thoughts {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 1 0;
    }
    .ab-playbooks {
        color: $success;
        margin: 0 0 1 0;
    }
    AgentBrain ProgressBar {
        height: 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state: str = "loading"
        self._repetition_score: float | None = None
        self._memory_pressure: float | None = None  # 0-1
        self._tool_calls: list[str] = []
        self._files: dict[str, str] = {}
        self._thoughts: list[str] = []
        self._playbooks: list[str] = []
        self._cost: float = 0.0
        self._steps: int = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("◈ AGENT BRAIN", classes="ab-heading")
            yield Static("⏳ Loading", id="ab-state", classes="ab-state")
            yield Static("─" * 28, classes="ab-divider")

            yield Static("REPETITION", classes="ab-heading")
            yield ProgressBar(
                total=100,
                show_eta=False,
                id="ab-rep-bar",
            )
            yield Static("—", id="ab-rep-label", classes="ab-tool-item")

            yield Static("MEMORY", classes="ab-heading")
            yield ProgressBar(
                total=100,
                show_eta=False,
                id="ab-mem-bar",
            )

            yield Static("─" * 28, classes="ab-divider")
            yield Static("RECENT TOOLS", classes="ab-heading")
            yield Static("(none)", id="ab-tools", classes="ab-tools")

            yield Static("─" * 28, classes="ab-divider")
            yield Static("FILES", classes="ab-heading")
            yield Static("(none)", id="ab-files", classes="ab-files")

            yield Static("─" * 28, classes="ab-divider")
            yield Static("THOUGHTS", classes="ab-heading")
            yield Static("(none)", id="ab-thoughts", classes="ab-thoughts")

            yield Static("─" * 28, classes="ab-divider")
            yield Static("PLAYBOOKS", classes="ab-heading")
            yield Static("(none)", id="ab-playbooks", classes="ab-playbooks")

    def update_state(self, state: str) -> None:
        self._state = state
        self._render_state()

    def update_repetition_score(self, score: float | None) -> None:
        """Score 0.0-1.0; None = unknown."""
        self._repetition_score = score
        self._render_repetition()

    def update_memory_pressure(self, pressure: float | None) -> None:
        """Pressure 0.0-1.0; None = unknown."""
        self._memory_pressure = pressure
        self._render_memory()

    def add_tool_call(self, label: str) -> None:
        self._tool_calls.append(label)
        self._tool_calls = self._tool_calls[-8:]
        self._render_tools()

    def track_file(self, path: str, action: str) -> None:
        self._files[path] = action
        self._render_files()

    def add_thought(self, thought: str) -> None:
        short = thought[:90].strip()
        if short and (not self._thoughts or self._thoughts[-1] != short):
            self._thoughts.append(short)
        self._thoughts = self._thoughts[-4:]
        self._render_thoughts()

    def set_playbooks(self, playbooks: list[str]) -> None:
        self._playbooks = playbooks
        self._render_playbooks()

    def update_cost_steps(self, cost: float, steps: int) -> None:
        self._cost = cost
        self._steps = steps

    def _render_state(self) -> None:
        try:
            label = _STATE_LABELS.get(self._state, self._state)
            state_widget = self.query_one("#ab-state", Static)
            state_widget.update(f"● {label}")
            if self._repetition_score is not None and self._repetition_score >= 0.6:
                state_widget.add_class("stuck-warning")
            else:
                state_widget.remove_class("stuck-warning")
        except Exception:
            pass

    def _render_repetition(self) -> None:
        try:
            bar = self.query_one("#ab-rep-bar", ProgressBar)
            label = self.query_one("#ab-rep-label", Static)
            if self._repetition_score is None:
                bar.update(progress=0)
                label.update("—")
                return
            pct = int(self._repetition_score * 100)
            bar.update(progress=min(pct, 100))
            if self._repetition_score >= 0.8:
                label.update(f"⚠ Stuck risk: {pct}%")
            elif self._repetition_score >= 0.5:
                label.update(f"↻ Repetition: {pct}%")
            else:
                label.update(f"OK ({pct}%)")
        except Exception:
            pass

    def _render_memory(self) -> None:
        try:
            bar = self.query_one("#ab-mem-bar", ProgressBar)
            if self._memory_pressure is None:
                bar.update(progress=0)
                return
            pct = int(self._memory_pressure * 100)
            bar.update(progress=min(pct, 100))
        except Exception:
            pass

    def _render_tools(self) -> None:
        try:
            w = self.query_one("#ab-tools", Static)
            if not self._tool_calls:
                w.update("(none)")
                return
            lines = self._tool_calls[-6:]
            w.update("\n".join(lines))
        except Exception:
            pass

    def _render_files(self) -> None:
        try:
            w = self.query_one("#ab-files", Static)
            if not self._files:
                w.update("(none)")
                return
            icons = {"edit": "~", "write": "+", "read": "r", "browse": "🌐", "run": "$"}
            lines = []
            for path, action in list(self._files.items())[-8:]:
                icon = icons.get(action, "?")
                name = path.replace("\\", "/").split("/")[-1]
                lines.append(f"{icon} {name}")
            w.update("\n".join(lines))
        except Exception:
            pass

    def _render_thoughts(self) -> None:
        try:
            w = self.query_one("#ab-thoughts", Static)
            if not self._thoughts:
                w.update("(none)")
                return
            wrapped = []
            for t in self._thoughts:
                if len(t) > 26:
                    words = t.split()
                    line = ""
                    for wrd in words:
                        if len(line) + len(wrd) + 1 > 26:
                            if line:
                                wrapped.append(line)
                            line = wrd
                        else:
                            line = (line + " " + wrd).strip()
                    if line:
                        wrapped.append(line)
                else:
                    wrapped.append(t)
            w.update("\n".join(wrapped[-6:]))
        except Exception:
            pass

    def _render_playbooks(self) -> None:
        try:
            w = self.query_one("#ab-playbooks", Static)
            if not self._playbooks:
                w.update("(none)")
                return
            w.update("\n".join(f"• {p}" for p in self._playbooks))
        except Exception:
            pass
