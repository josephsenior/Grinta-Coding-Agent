"""Help screen — shows keyboard shortcuts and navigation guide."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Static,
    TabPane,
    TabbedContent,
    Markdown,
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
    .help-section {
        margin: 1 0;
    }
    .help-title {
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }
    .help-keybinding {
        color: $primary;
        text-style: bold;
    }
    .help-action {
        color: $text;
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
            yield Static("Keyboard shortcuts and navigation guide", classes="help-description")
            
            with TabbedContent(initial="shortcuts"):
                with TabPane("Keyboard Shortcuts", id="shortcuts"):
                    yield self._create_shortcuts_content()
                
                with TabPane("Navigation", id="navigation"):
                    yield self._create_navigation_content()
                
                with TabPane("Model & Config", id="config"):
                    yield self._create_config_content()
        
        yield Footer()

    def _create_shortcuts_content(self) -> ComposeResult:
        """Create keyboard shortcuts content."""
        shortcuts_md = """
## Home Screen

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+N` | New conversation | Create a new conversation |
| `Ctrl+S` | Settings | Open settings screen |
| `Ctrl+Q` | Quit | Exit application |
| `R` | Refresh | Refresh conversation list |
| `D` | Delete | Delete selected conversation |
| `Enter` | Select | Open selected conversation or create new |
| `↑/↓` | Navigate | Move through conversation list |

## Chat Screen

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+Q` | Back to Home | Return to home screen |
| `Ctrl+D` | View Diff | Show file changes in diff viewer |
| `Ctrl+X` | Stop Agent | Stop the currently running agent |
| `Escape` | Cancel | Cancel current confirmation dialog |
| `Enter` | Confirm | Confirm agent action when prompted |
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
| `↑/↓` | Scroll | Navigate through file changes |
| `Enter` | Select | View specific file diff |

## Global Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+C` | Quit | Emergency exit from any screen |
| `?` | Help | Show this help screen (from any screen) |
| `H` | Help | Show this help screen (from any screen) |
| `Ctrl+L` | Clear | Clear screen content where applicable |
"""
        return Markdown(shortcuts_md)

    def _create_navigation_content(self) -> ComposeResult:
        """Create navigation guide content."""
        navigation_md = """
## Screen Flow

```
Home Screen ──────┐
    ↕             │
Chat Screen ──────┤
    └─ Diff Viewer │
                  │
Settings ─────────┘
```

## Basic Navigation

1. **Start**: Application opens to Home Screen
2. **Create**: Type a conversation name and press Enter
3. **Chat**: Type messages in the input box at bottom
4. **Agent Actions**: Approve/reject when prompted
5. **View Changes**: Press `Ctrl+D` to see file modifications
6. **Settings**: Press `Ctrl+S` from home to configure model/keys
7. **Return**: Press `Escape` or `Ctrl+Q` to go back

## Input Areas

### Chat Input
- Type your message or question
- Press `Enter` to send
- Use `Shift+Enter` for multi-line messages

### Confirmation Bar
- Shows when agent needs approval
- Press `Enter` to approve
- Press `Escape` to reject

### Settings Fields
- Use `Tab` to move between fields
- Press `Enter` to open dropdowns
- Type to enter text values

## Quick Tips

- **Scroll**: Use arrow keys or mouse wheel in list views
- **Multi-select**: Not yet supported, use one action at a time  
- **Long output**: Agent outputs auto-scroll to show latest
- **Status**: Top bar shows current model, cost, and agent status
- **Help**: Press `?` or `H` from any screen to return here
"""
        return Markdown(navigation_md)

    def _create_config_content(self) -> ComposeResult:
        """Create configuration help content."""
        config_md = """
## Model Selection

You can switch models in Settings or by editing `config.toml`:

### Cloud Models
- **GPT-4**: `gpt-4o` (best balance)
- **Claude**: `claude-3-5-sonnet-20241022` (best for code)
- **Gemini**: `gemini/gemini-1.5-pro` (good context)

### Local Models (Ollama)
- **Llama 3.2**: `ollama/llama3.2` (fast, good quality)
- **DeepSeek Coder**: `ollama/deepseek-coder` (coding specialist)
- **Code Llama**: `ollama/codellama` (code generation)

## Autonomy Levels

Control how much the agent can do automatically:

- **Supervised**: Ask permission for every action (safest)
- **Balanced**: Ask for high-risk actions only (recommended)  
- **Full**: Run completely automatically (fastest)

## Memory Management

Choose how conversation history is managed:

- **Smart**: Automatically picks best strategy (default)
- **LLM**: Use AI to summarize old messages (best quality)
- **Recent**: Keep only recent messages (cheapest)
- **No Condensing**: Keep everything (debug only)

## Cost Controls

Set budgets to prevent runaway charges:

- **Max Budget**: Dollar limit per conversation
- **Token Tracking**: Real-time cost display in status bar
- **Model Switching**: Use cheaper models for simple tasks

## Local Setup

For offline usage:

1. Install Ollama: https://ollama.ai  
2. Pull a model: `ollama pull llama3.2`
3. Start Ollama: `ollama serve`
4. Configure Forge: Set model to `ollama/llama3.2` in Settings

See USER_GUIDE.md for complete configuration instructions.
"""
        return Markdown(config_md)

    def action_go_back(self) -> None:
        """Go back to the previous screen."""
        self.dismiss()