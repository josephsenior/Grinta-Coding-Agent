"""Transcript message and streaming indicator widgets."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.theme import (
    CLR_REASONING_SNAP,
    NAVY_BG_TRANSCRIPT_ACTIVE,
    NAVY_BG_TRANSCRIPT_BLOCK,
    NAVY_BG_USER,
    NAVY_TEXT_BODY,
    NAVY_TEXT_LIVE,
    NAVY_TEXT_LIVE_ACTIVE,
    NAVY_TEXT_USER,
)
from backend.cli.tui.image_attachments import image_attachment_status_text
from backend.cli.tui.transcript_typography import (
    THINKING_LABEL,
    USER_PIPE,
    assemble_thinking_renderable,
)


class UserMessage(Static):
    """User message display in the transcript."""

    DEFAULT_CSS = f"""
    UserMessage {{
        width: 100%;
        height: auto;
        margin: 1 0 2 0;
        padding: 1 2 2 2;
        background: {NAVY_BG_USER};
        border: transparent;
        border-right: wide {USER_PIPE};
        color: {NAVY_TEXT_USER};
    }}
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
        self.styles.border_right = ('wide', USER_PIPE)


class AgentMessage(Static):
    """Agent response display in the transcript — plain text, no card chrome."""

    DEFAULT_CSS = f"""
    AgentMessage {{
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        background: transparent;
        color: {NAVY_TEXT_BODY};
    }}
    """

    def __init__(
        self,
        text: str,
        *,
        renderable: Any | None = None,
        plain: bool = True,
        id: str | None = None,
    ) -> None:
        if renderable is None:
            from backend.cli.tui.renderer.prep import prep_markdown

            renderable = prep_markdown(text)
        super().__init__(renderable, id=id)
        if plain:
            self.add_class('-plain')

    def update_message(self, text: str, *, renderable: Any | None = None) -> None:
        """Update message content dynamically."""
        if renderable is None:
            from backend.cli.tui.renderer.prep import prep_markdown

            renderable = prep_markdown(text)
        self.update(renderable)


class LiveResponse(Container):
    """In-flight assistant response — streams with the same markdown richness as finals."""

    DEFAULT_CSS = f"""
    LiveResponse {{
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        background: transparent;
    }}
    LiveResponse > #live-content {{
        width: 100%;
        height: auto;
        color: {NAVY_TEXT_LIVE};
    }}
    LiveResponse.-streaming > #live-content {{
        color: {NAVY_TEXT_LIVE_ACTIVE};
    }}
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._pending_text: str = ''

    def compose(self) -> ComposeResult:
        yield Static('', id='live-content')

    def on_mount(self) -> None:
        if self._pending_text:
            self.set_streaming_content(self._pending_text)

    def _live_content(self) -> Static | None:
        try:
            return self.query_one('#live-content', Static)
        except Exception:
            return None

    def set_streaming_renderable(self, renderable: Any) -> None:
        """Update visible streaming content."""
        content = self._live_content()
        if content is None:
            return
        if renderable is None or renderable == '':
            content.update('')
            self.remove_class('-streaming')
            return
        self.add_class('-streaming')
        content.update(renderable)

    def set_streaming_content(self, text: str) -> None:
        """Highlight in-flight assistant markdown like finalized AgentMessage rows."""
        if not text:
            self._pending_text = ''
            content = self._live_content()
            if content is not None:
                content.update('')
            self.remove_class('-streaming')
            return
        from backend.cli.tui.renderer.prep import prep_live_response_renderable

        renderable = prep_live_response_renderable(text)
        content = self._live_content()
        if content is None:
            self._pending_text = text
            self.add_class('-streaming')
            return
        self._pending_text = ''
        self.add_class('-streaming')
        content.update(renderable)

    def set_streaming_text(self, text: str) -> None:
        """Fallback plain-text update when highlighted prep is unavailable."""
        if not text:
            self._pending_text = ''
            content = self._live_content()
            if content is not None:
                content.update('')
            self.remove_class('-streaming')
            return
        content = self._live_content()
        if content is None:
            self._pending_text = text
            self.add_class('-streaming')
            return
        self._pending_text = ''
        self.add_class('-streaming')
        content.update(Text(text, style='#d5dee8'))


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
        background: {NAVY_BG_TRANSCRIPT_BLOCK};
        border-left: solid {THINKING_LABEL};
        padding: 0 1 0 2;
    }}
    ThinkingIndicator.-hidden {{
        display: none;
    }}
    ThinkingIndicator.-streaming {{
        background: {NAVY_BG_TRANSCRIPT_ACTIVE};
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

    def _update_display_lightweight(self, content: Static, full_text: str) -> None:
        from backend.cli.tui.renderer.prep import prep_streaming_renderable

        content.remove_class('-hidden')
        body = prep_streaming_renderable(full_text, base_text_style=CLR_REASONING_SNAP)
        content.update(
            assemble_thinking_renderable(
                self._current_action,
                THINKING_LABEL,
                body,
            )
        )

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
