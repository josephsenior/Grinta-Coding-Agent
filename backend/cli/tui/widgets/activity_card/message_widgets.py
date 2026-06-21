"""Transcript message and streaming indicator widgets."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.theme import CLR_REASONING_SNAP
from backend.cli.tui.transcript_typography import THINKING_LABEL
from backend.cli.tui.image_attachments import image_attachment_status_text


class TurnCompletion(Static):
    """Thin turn separator — matches OrientLine / ThinkingIndicator chrome."""

    _PIPE = '#3d5a4a'
    _LABEL = '#5a7a6a'
    _DURATION = '#9aa8b8'

    DEFAULT_CSS = """
    TurnCompletion {
        width: 100%;
        height: auto;
        margin: 1 0 2 0;
        padding: 0 1 0 2;
        border: transparent;
        border-left: solid #3d5a4a;
        background: #090d18;
    }
    """

    def __init__(
        self,
        duration: str,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.styles.border_left = ('solid', self._PIPE)
        self.update(
            Text.assemble(
                ('Finished in: ', self._LABEL),
                (duration, self._DURATION),
            )
        )


class UserMessage(Static):
    """User message display in the transcript."""

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        height: auto;
        margin: 1 0 2 0;
        padding: 1 2 2 2;
        background: #0d1522;
        border: transparent;
        border-right: solid #5a6a8a;
        color: #e9e9e9;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        image_count: int = 0,
        id: str | None = None,
    ) -> None:
        from backend.cli.tui.renderer.prep import prep_markdown

        body = (text or '').rstrip()
        parts: list[Any] = []
        if image_count > 0:
            from backend.cli.tui.transcript_typography import TX_META

            parts.append(
                Text(
                    image_attachment_status_text(image_count),
                    style=TX_META,
                )
            )
        if body:
            parts.append(prep_markdown(body))
        if not parts:
            renderable: Any = Text('')
        elif len(parts) == 1:
            renderable = parts[0]
        else:
            from rich.console import Group

            renderable = Group(*parts)
        super().__init__(renderable, id=id)


class AgentMessage(Static):
    """Agent response display in the transcript."""

    DEFAULT_CSS = """
    AgentMessage {
        width: 100%;
        height: auto;
        margin: 1 0 2 0;
        padding: 1 2 2 2;
        border: transparent;
        border-left: solid #3d4a66;
        background: #090d18;
        color: #c8d4e8;
    }
    AgentMessage.-plain {
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        background: transparent;
        color: #c8d4e8;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        renderable: Any | None = None,
        plain: bool = False,
        id: str | None = None,
    ) -> None:
        from backend.cli.tui.transcript_typography import AGENT_PIPE

        if renderable is None:
            from backend.cli.tui.renderer.prep import prep_markdown

            renderable = prep_markdown(text)
        super().__init__(renderable, id=id)
        if plain:
            self.add_class('-plain')
        else:
            self.styles.border_left = ('solid', AGENT_PIPE)

    def update_message(self, text: str, *, renderable: Any | None = None) -> None:
        """Update message content dynamically."""
        if renderable is None:
            from backend.cli.tui.renderer.prep import prep_markdown

            renderable = prep_markdown(text)
        self.update(renderable)


class LiveResponse(Static):
    """In-flight assistant response with lightweight streaming affordances."""

    DEFAULT_CSS = """
    LiveResponse {
        width: 100%;
        height: auto;
        margin: 0 0 2 0;
        padding: 1 1 1 2;
        border: transparent;
        border-left: solid #3d4a66;
        background: #090d18;
        color: #b8c4d8;
    }
    LiveResponse.-streaming {
        color: #d5dee8;
    }
    """

    def set_streaming_renderable(self, renderable: Any) -> None:
        """Update visible streaming content."""
        if renderable is None or renderable == '':
            self.update('')
            self.remove_class('-streaming')
            return
        self.add_class('-streaming')
        self.update(renderable)

    def set_streaming_text(self, text: str) -> None:
        """Fallback plain-text update when highlighted prep is unavailable."""
        if not text:
            self.update('')
            self.remove_class('-streaming')
            return
        self.add_class('-streaming')
        self.update(Text(text, style='#d5dee8'))


class ThinkingIndicator(Container):
    """Thinking/reasoning indicator with inline prefix.

    Shows the thinking content directly with a "Thinking:" prefix
    inline on the first line. No collapse/expand, no duration display.
    Supports syntax highlighting for code blocks within thinking content.
    """

    DEFAULT_CSS = f"""
    ThinkingIndicator {{
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: transparent;
        background: #090d18;
        border-left: solid {THINKING_LABEL};
        padding: 0 1 0 2;
    }}
    ThinkingIndicator.-hidden {{
        display: none;
    }}
    ThinkingIndicator.-streaming {{
        background: #0a101c;
    }}
    ThinkingIndicator > #thinking-content {{
        width: 100%;
        height: auto;
    }}
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._thoughts: list[str] = []
        self._current_action: str = 'Thinking'
        self.styles.border_left = ('solid', THINKING_LABEL)
        self.add_class('-hidden')

    def compose(self) -> ComposeResult:
        yield Static('', id='thinking-content')

    def start(self, action: str = 'Thinking') -> None:
        """Start the thinking indicator."""
        self._current_action = action
        self._thoughts = []
        self.remove_class('-hidden')
        self._update_display()

    def add_thought(self, thought: str) -> None:
        """Add a reasoning step."""
        self._thoughts.append(thought)
        self._update_display()

    def set_thoughts(self, text: str, *, streaming: bool = False) -> None:
        if streaming and text == getattr(self, '_last_stream_text', ''):
            return
        if streaming:
            self._last_stream_text = text
        else:
            self._last_stream_text = ''
        self._thoughts = text.split('\n')
        self._update_display(streaming=streaming)

    def stop(self) -> None:
        """Stop the thinking indicator."""
        self.add_class('-hidden')

    def finalize(self) -> None:
        """No-op for API compatibility."""

    def _thinking_prefix_renderable(self) -> Text:
        return Text.assemble((f'{self._current_action}: ', THINKING_LABEL))

    def _update_display_lightweight(self, content: Static, full_text: str) -> None:
        from rich.console import Group

        from backend.cli.tui.renderer.prep import prep_streaming_renderable

        content.remove_class('-hidden')
        body = prep_streaming_renderable(full_text, base_text_style=CLR_REASONING_SNAP)
        content.update(Group(self._thinking_prefix_renderable(), body))

    def _update_display(self, *, streaming: bool = False) -> None:
        if not self._thoughts:
            return

        full_text = '\n'.join(self._thoughts)

        try:
            content = self.query_one('#thinking-content', Static)
        except Exception:
            return

        if streaming:
            self.add_class('-streaming')
        else:
            self.remove_class('-streaming')

        self._update_display_lightweight(content, full_text)

    def on_mount(self) -> None:
        self._update_display()
