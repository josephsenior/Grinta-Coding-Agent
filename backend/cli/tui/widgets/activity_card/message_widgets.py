"""Transcript message and streaming indicator widgets."""

from __future__ import annotations

import re
from typing import Any

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.syntax_theme import get_grinta_rich_syntax_theme
from backend.cli.theme import CLR_REASONING_SNAP


class TurnCompletion(Static):
    """Thin full-width completion marker between agent turns."""

    DEFAULT_CSS = """
    TurnCompletion {
        width: 100%;
        height: 1;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #071b21;
        color: #8f9fc1;
    }
    """

    def __init__(
        self,
        duration: str,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.update(f'[#5eead4]Finished in:[/] [#c8d4e8]{duration}[/]')


class UserMessage(Static):
    """User message display in the transcript."""

    def __init__(self, text: str, *, id: str | None = None) -> None:
        from backend.cli.tui.renderer.prep import prep_markdown

        body = (text or '').rstrip()
        renderable = prep_markdown(body) if body else Text('')
        super().__init__(renderable, id=id)


class AgentMessage(Static):
    """Agent response display in the transcript."""

    def __init__(
        self,
        text: str,
        *,
        renderable: Any | None = None,
        id: str | None = None,
    ) -> None:
        if renderable is None:
            from backend.cli.tui.renderer.prep import prep_markdown

            renderable = prep_markdown(text)
        super().__init__(renderable, id=id)

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
        margin: 0 0 1 0;
        padding: 0 1 0 2;
        background: #070b14;
        border-left: solid #3d5a80;
        color: #b8c4d8;
    }
    LiveResponse.-streaming {
        color: #d5dee8;
        border-left: solid #5eead4;
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

    DEFAULT_CSS = """
    ThinkingIndicator {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: transparent;
        background: #090d18;
        border-left: solid #3d5a80;
        padding: 0 1 0 2;
    }
    ThinkingIndicator.-hidden {
        display: none;
    }
    ThinkingIndicator.-streaming {
        background: #0a101c;
        border-left: solid #5eead4;
    }
    ThinkingIndicator > #thinking-content {
        width: 100%;
        height: auto;
    }
    ThinkingIndicator .code-block {
        margin: 1 0;
        padding: 0 1;
        background: #0d1525;
    }
    """

    # Pattern to match fenced code blocks: ```language\n...\n```
    _CODE_BLOCK_PATTERN = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._thoughts: list[str] = []
        self._current_action: str = 'Thinking'
        self._code_block_container: Any = None
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

    def _has_code_blocks(self, text: str) -> bool:
        """Check if text contains fenced code blocks."""
        return bool(self._CODE_BLOCK_PATTERN.search(text))

    def _parse_text_segments(self, text: str) -> list[tuple[str, Any]]:
        segments = []
        last_end = 0
        for match in self._CODE_BLOCK_PATTERN.finditer(text):
            if match.start() > last_end:
                plain_text = text[last_end : match.start()]
                if plain_text.strip():
                    segments.append(('plain', plain_text))
            language = match.group(1) or 'text'
            code_content = match.group(2)
            segments.append(('code', (language, code_content)))
            last_end = match.end()
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining.strip():
                segments.append(('plain', remaining))
        return segments

    def _build_segment_widgets(self, segments: list[tuple[str, Any]]) -> list[Any]:
        from textual.widgets import Static as TextualStatic

        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = CLR_REASONING_SNAP
        children: list[Any] = []

        for seg_type, seg_content in segments:
            if seg_type == 'plain':
                if not children:
                    parts = [
                        (prefix, prefix_color),
                        (seg_content, text_color),
                    ]
                    text_widget = TextualStatic(Text.assemble(*parts))
                else:
                    text_widget = TextualStatic(Text(seg_content, style=text_color))
                children.append(text_widget)
            else:
                language, code = seg_content
                syntax = Syntax(
                    code,
                    language,
                    theme=get_grinta_rich_syntax_theme(),
                    background_color='#0d1525',
                    padding=(0, 1),
                    word_wrap=True,
                )
                code_widget = TextualStatic(syntax)
                code_widget.add_class('code-block')
                children.append(code_widget)
        return children

    def _render_with_code_blocks(self, text: str) -> tuple[Any, list[Any]]:
        """Render text with syntax-highlighted code blocks.

        Returns a tuple of (container, children_widgets) to be mounted by caller.
        """
        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = CLR_REASONING_SNAP

        segments = self._parse_text_segments(text)

        if not segments:
            parts = [(prefix, prefix_color), (text, text_color)]
            return Text.assemble(*parts), []

        from textual.containers import Vertical

        container = Vertical()
        children = self._build_segment_widgets(segments)
        return container, children

    def _build_thoughts_text_parts(self) -> list[tuple[str, str]]:
        prefix = f'{self._current_action}: '
        prefix_color = '#42a394'
        text_color = CLR_REASONING_SNAP
        lines = self._thoughts
        parts: list[tuple[str, str]] = [
            (prefix, prefix_color),
            (lines[0], text_color),
        ]
        for line in lines[1:]:
            parts.append(('\n  ', text_color))
            parts.append((line, text_color))
        return parts

    def _update_display_streaming(self, content: Static) -> None:
        from rich.console import Group

        from backend.cli.tui.renderer.prep import prep_streaming_renderable

        content.remove_class('-hidden')
        if self._code_block_container is not None:
            self._code_block_container.remove()
            self._code_block_container = None

        full_text = '\n'.join(self._thoughts)
        prefix_color = '#42a394'
        prefix = Text.assemble((f'{self._current_action}: ', prefix_color))

        if '```' in full_text or '`' in full_text:
            body = prep_streaming_renderable(
                full_text, base_text_style=CLR_REASONING_SNAP
            )
            content.update(Group(prefix, body))
            return

        parts = self._build_thoughts_text_parts()
        content.update(Text.assemble(*parts))

    def _update_display_with_code_blocks(self, content: Static, full_text: str) -> None:
        from textual.containers import Vertical

        content.add_class('-hidden')
        if self._code_block_container is None:
            self._code_block_container = Vertical()
            self.mount(self._code_block_container)
        for child in list(self._code_block_container.children):
            child.remove()
        _, children = self._render_with_code_blocks(full_text)
        for child in children:
            self._code_block_container.mount(child)

    def _update_display_plain(self, content: Static) -> None:
        content.remove_class('-hidden')
        if self._code_block_container is not None:
            self._code_block_container.remove()
            self._code_block_container = None
        parts = self._build_thoughts_text_parts()
        content.update(Text.assemble(*parts))

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
            self._update_display_streaming(content)
            return

        self.remove_class('-streaming')

        if self._has_code_blocks(full_text):
            self._update_display_with_code_blocks(content, full_text)
        else:
            self._update_display_plain(content)

    def on_mount(self) -> None:
        self._update_display()
