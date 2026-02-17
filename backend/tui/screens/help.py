"""Help screen — shows keyboard shortcuts and navigation guide."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Markdown,
    Static,
    TabPane,
    TabbedContent,
)


class HelpScreen(Screen[None]):
    """Help screen showing keyboard shortcuts and usage information."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("q", "go_back", "Back", show=False),
        Binding("ctrl+q", "go_back", "Back", show=False),
    ]

    CSS = """
    #help-outer {
        height: 100%;
        padding: 1 2;
    }
    .help-title {
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }
    .help-description {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        """Create the help screen layout."""
        yield Header(show_clock=True)
        with Vertical(id="help-outer"):
            yield Static("⚒  Forge Help", classes="help-title")
            yield Static(
                "Keyboard shortcuts and navigation guide",
                classes="help-description",
            )

            with TabbedContent(initial="shortcuts"):
                with TabPane("Keyboard Shortcuts", id="shortcuts"):
                    yield self._create_shortcuts_content()

                with TabPane("Navigation", id="navigation"):
                    yield self._create_navigation_content()

                with TabPane("Model & Config", id="config"):
                    yield self._create_config_content()

        yield Footer()

    # -- helpers (each returns a single Markdown widget) ----------

    def _create_shortcuts_content(self) -> Markdown:
        """Keyboard shortcuts reference."""
        return Markdown(
            """\
## Home Screen

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+N` | New conversation | Create a new conversation |
| `Ctrl+S` | Settings | Open settings screen |
| `Ctrl+Q` | Quit | Exit application |
| `R` | Refresh | Refresh conversation list (when list focused) |
| `D` | Delete | Delete selected conversation (when list focused) |
| `Enter` | Select | Open selected conversation or create new |
| `↑ / ↓` | Navigate | Move through conversation list |

## Chat Screen

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+Q` | Back to Home | Return to home screen |
| `Ctrl+D` | View Diff | Show file changes in diff viewer |
| `Ctrl+X` | Stop Agent | Stop the currently running agent |
| `Escape` | Cancel | Cancel current confirmation dialog |
| `Enter` | Confirm / Send | Confirm agent action or send message |
| `Tab` | Navigate | Move between input and messages |

## Settings Screen

| Key | Action | Description |
|-----|--------|-------------|
| `Escape` | Back | Return to previous screen |
| `Ctrl+S` | Save | Save current settings |
| `Tab` | Navigate | Move between settings fields |
| `Enter` | Select | Select dropdown options |

## Diff Viewer

| Key | Action | Description |
|-----|--------|-------------|
| `Escape` | Back | Return to chat screen |
| `R` | Refresh | Refresh diff display |
| `↑ / ↓` | Scroll | Navigate through file changes |
| `Enter` | Select | View specific file diff |

## Global Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+C` | Quit | Emergency exit from any screen |
| `F1` | Help | Show this help screen (from any screen) |
| `Ctrl+L` | Clear | Clear screen content where applicable |
"""
        )

    def _create_navigation_content(self) -> Markdown:
        """Navigation guide."""
        return Markdown(
            """\
## Screen Flow

```
Home Screen ──────┐
    ↕             │
Chat Screen ──────┤
    └─ Diff Viewer│
                  │
Settings ─────────┘
    ↕
Help ─────────────┘
```

## Basic Navigation

1. **Start** — Application opens to the Home Screen.
2. **Create** — Type a conversation name and press `Enter`.
3. **Chat** — Type messages in the input box at the bottom.
4. **Agent Actions** — Approve or reject when prompted.
5. **View Changes** — Press `Ctrl+D` to see file modifications.
6. **Settings** — Press `Ctrl+S` from Home to configure model/keys.
7. **Return** — Press `Escape` or `Ctrl+Q` to go back.

## Input Areas

### Chat Input
- Type your message or question and press `Enter` to send.

### Confirmation Bar
- Shows when the agent needs approval.
- Press `Enter` to approve, `Escape` to reject.

### Settings Fields
- Use `Tab` to move between fields.
- Press `Enter` to open dropdowns.

## Quick Tips

- **Scroll**: Use arrow keys or mouse wheel in list views.
- **Long output**: Agent outputs auto-scroll to the latest line.
- **Status**: The status bar shows current model, cost, and agent state.
- **Help**: Press `F1` from any screen to open this help.
"""
        )

    def _create_config_content(self) -> Markdown:
        """Configuration reference."""
        return Markdown(
            """\
## Model Selection

Switch models in **Settings** or by editing `config.toml`.

### Cloud Models
| Provider | Model ID | Notes |
|----------|----------|-------|
| OpenAI | `gpt-5.3-turbo` | Best balance of speed/quality |
| Anthropic | `claude-4.6-sonnet` | Best for code tasks |
| Google | `gemini/gemini-3-pro` | Large context window |
| xAI | `grok-4.1` | Strong reasoning |

### Local Models (Ollama)
| Model | ID | Notes |
|-------|----|-------|
| Llama 3.2 | `ollama/llama3.2` | Fast, good quality |
| DeepSeek Coder | `ollama/deepseek-coder` | Coding specialist |
| Code Llama | `ollama/codellama` | Code generation |

## Autonomy Levels

- **Supervised** — Ask permission for every action (safest).
- **Balanced** — Ask only for high-risk actions (recommended).
- **Full** — Run completely automatically (fastest).

## Memory Management

- **Smart** — Automatically picks the best strategy (default).
- **LLM** — Use AI to summarise old messages (best quality).
- **Recent** — Keep only recent messages (cheapest).
- **No Condensing** — Keep everything (debug only).

## Cost Controls

- **Max Budget** — Dollar limit per conversation.
- **Token Tracking** — Real-time cost display in the status bar.
- **Model Switching** — Use cheaper models for simple tasks.

## Local Setup

1. Install Ollama: <https://ollama.ai>
2. Pull a model: `ollama pull llama3.2`
3. Start Ollama: `ollama serve`
4. Set model to `ollama/llama3.2` in Settings.

See `USER_GUIDE.md` for complete configuration instructions.
"""
        )

    # ── actions ───────────────────────────────────────────────────

    def action_go_back(self) -> None:
        """Go back to the previous screen."""
        self.dismiss()
