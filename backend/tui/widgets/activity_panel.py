"""Activity panel — right-side sidebar showing session activity.

Displays:
- Running cost and step count
- Files the agent has touched this session (last 12)
- Recent "think" thoughts from the agent (last 4)
- Active playbooks for this session

All updates are driven by ``track_file``, ``add_thought``, etc. which
are called from ``ChatScreen`` as events arrive.  The widget uses a single
``Static`` per section and replaces its content in-place to avoid
Textual DOM churn.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


class ActivityPanel(Widget):
    """Right-side sidebar widget tracking live session activity."""

    DEFAULT_CSS = """
    ActivityPanel {
        width: 30;
        border-left: vkey $primary;
        padding: 0 1;
        background: $surface-darken-1;
        overflow-y: scroll;
    }
    .ap-heading {
        text-style: bold;
        color: $accent;
        margin: 1 0 0 0;
    }
    .ap-stat {
        color: $accent;
        text-style: bold;
        margin: 0 0 1 0;
    }
    .ap-divider {
        color: $primary-darken-1;
    }
    .ap-files {
        color: $text;
        margin: 0 0 1 0;
    }
    .ap-thoughts {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 1 0;
    }
    .ap-playbooks {
        color: $success;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files: dict[str, str] = {}     # path -> action verb
        self._thoughts: list[str] = []
        self._playbooks: list[str] = []
        self._cost: float = 0.0
        self._steps: int = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("◈ SESSION", classes="ap-heading")
            yield Static("💰 $0.0000   🔁 0 steps", id="ap-stats", classes="ap-stat")
            yield Static("─" * 26, classes="ap-divider")
            yield Static("PLAYBOOKS", classes="ap-heading")
            yield Static("(loading…)", id="ap-playbooks", classes="ap-playbooks")
            yield Static("─" * 26, classes="ap-divider")
            yield Static("FILES TOUCHED", classes="ap-heading")
            yield Static("(none yet)", id="ap-files", classes="ap-files")
            yield Static("─" * 26, classes="ap-divider")
            yield Static("THOUGHTS", classes="ap-heading")
            yield Static("(none yet)", id="ap-thoughts", classes="ap-thoughts")

    # ── public API ────────────────────────────────────────────────

    def track_file(self, path: str, action: str) -> None:
        """Record a file the agent interacted with."""
        self._files[path] = action
        self._render_files()

    def add_thought(self, thought: str) -> None:
        """Record an agent thought (keep last 4)."""
        short = thought[:90].strip()
        if short and (not self._thoughts or self._thoughts[-1] != short):
            self._thoughts.append(short)
        self._thoughts = self._thoughts[-4:]
        self._render_thoughts()

    def update_cost(self, cost: float) -> None:
        self._cost = cost
        self._render_stats()

    def update_steps(self, steps: int) -> None:
        self._steps = steps
        self._render_stats()

    def set_playbooks(self, playbooks: list[str]) -> None:
        """Replace the active playbook list."""
        self._playbooks = playbooks
        self._render_playbooks()

    # ── render helpers ────────────────────────────────────────────

    def _render_stats(self) -> None:
        try:
            self.query_one("#ap-stats", Static).update(
                f"💰 ${self._cost:.4f}   🔁 {self._steps} steps"
            )
        except Exception:
            pass

    def _render_playbooks(self) -> None:
        try:
            widget = self.query_one("#ap-playbooks", Static)
            if self._playbooks:
                lines = "\n".join(f"• {p}" for p in self._playbooks)
            else:
                lines = "(none)"
            widget.update(lines)
        except Exception:
            pass

    def _render_files(self) -> None:
        try:
            widget = self.query_one("#ap-files", Static)
            if not self._files:
                widget.update("(none yet)")
                return
            icons = {"edit": "~", "write": "+", "read": "r", "browse": "🌐", "run": "$"}
            lines: list[str] = []
            for path, action in list(self._files.items())[-12:]:
                icon = icons.get(action, "?")
                name = path.replace("\\", "/").split("/")[-1]
                lines.append(f"{icon} {name}")
            widget.update("\n".join(lines))
        except Exception:
            pass

    def _render_thoughts(self) -> None:
        try:
            widget = self.query_one("#ap-thoughts", Static)
            if not self._thoughts:
                widget.update("(none yet)")
                return
            # Wrap long thoughts at ~26 chars
            out: list[str] = []
            for t in self._thoughts:
                if len(t) > 26:
                    # simple word-wrap at 26
                    words = t.split()
                    line = ""
                    for w in words:
                        if len(line) + len(w) + 1 > 26:
                            if line:
                                out.append(line)
                            line = w
                        else:
                            line = (line + " " + w).strip()
                    if line:
                        out.append(line)
                    out.append("")  # blank line between thoughts
                else:
                    out.append(t)
                    out.append("")
            widget.update("\n".join(out).strip())
        except Exception:
            pass
