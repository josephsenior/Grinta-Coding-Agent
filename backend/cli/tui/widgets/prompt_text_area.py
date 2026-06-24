"""Prompt input widget with terminal leak sanitization and clipboard handling."""

from __future__ import annotations

from typing import Any

import pyperclip
from textual import events
from textual.widgets import TextArea


class PromptTextArea(TextArea):
    """Input area that routes arrow navigation to welcome suggestions when idle."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._previous_input_text = ''
        self._sanitizing_input = False

    def on_mount(self) -> None:
        # Host terminals can inject mouse CSI faster than reactive watchers run.
        self.set_interval(0.12, self._poll_sanitize_leaked_input)

    def on_focus(self, event: events.Focus) -> None:
        from backend.cli.win32_console import win32_flush_input_buffer

        win32_flush_input_buffer()

    def on_blur(self, event: events.Blur) -> None:
        from backend.cli.win32_console import win32_flush_input_buffer

        win32_flush_input_buffer()

    def _poll_sanitize_leaked_input(self) -> None:
        if self._sanitizing_input or self.read_only or not self.text:
            return
        from backend.cli.terminal_sanitize import looks_like_terminal_leak_fragment

        if looks_like_terminal_leak_fragment(self.text):
            self._apply_input_sanitize(source='poll')

    def _apply_input_sanitize(self, *, source: str = 'watch') -> bool:
        from backend.cli.terminal_sanitize import sanitize_prompt_input_text

        if self._sanitizing_input:
            return False
        cleaned = sanitize_prompt_input_text(self.text)
        if cleaned == self.text:
            return False
        self._sanitizing_input = True
        try:
            self._previous_input_text = cleaned
            self.text = cleaned
        finally:
            self._sanitizing_input = False
        return True

    def _resolve_grinta_screen(self) -> Any | None:
        """Return the main Grinta screen even when a modal/detail is stacked."""
        app = getattr(self, 'app', None)
        if app is not None:
            main = getattr(app, '_screen', None)
            if main is not None and hasattr(main, 'try_paste_clipboard_image'):
                return main
            screen = getattr(app, 'screen', None)
            if screen is not None and hasattr(screen, 'try_paste_clipboard_image'):
                return screen
        return getattr(self, 'screen', None)

    def _paste_target_screen(self) -> Any | None:
        return self._resolve_grinta_screen()

    def _try_remove_pending_image_attachment(self) -> bool:
        """Remove staged images when the input is empty (backspace/delete)."""
        screen = self._paste_target_screen()
        if screen is None or self.text.strip():
            return False
        remove_last = getattr(screen, 'remove_last_pending_image_attachment', None)
        if callable(remove_last) and remove_last():
            return True
        return False

    def _try_clear_pending_image_attachments_on_empty_text(
        self, previous: str, text: str
    ) -> None:
        """Clear staged images when the user deletes all typed text."""
        if not previous.strip() or text.strip():
            return
        screen = self._paste_target_screen()
        if screen is None:
            return
        clear_all = getattr(screen, 'clear_pending_image_attachments', None)
        if callable(clear_all):
            clear_all()

    async def _try_attach_clipboard_image(self) -> bool:
        """Attach a clipboard image or report why paste could not continue."""
        screen = self._paste_target_screen()
        if screen is None or not hasattr(screen, 'try_paste_clipboard_image'):
            return False
        if await screen.try_paste_clipboard_image():
            return True
        from backend.cli.tui.image_attachments import clipboard_likely_has_image

        if clipboard_likely_has_image():
            notify = getattr(screen, 'notify_warning', None)
            if callable(notify):
                notify(
                    'Clipboard contains an image but Grinta could not read it. '
                    'Try copying again or use the attach-images action.'
                )
            return True
        return False

    def watch_text(self, text: str) -> None:
        if self._apply_input_sanitize(source='watch'):
            return

        previous = self._previous_input_text
        self._previous_input_text = text
        self._try_clear_pending_image_attachments_on_empty_text(previous, text)
        screen = self._paste_target_screen()
        if screen is None:
            return
        refresh = getattr(screen, '_refresh_input_attachment_hint', None)
        if callable(refresh):
            refresh()

    def _paste_text_from_clipboard(self, event: events.Paste | None = None) -> None:
        try:
            clipboard = pyperclip.paste()
        except Exception:
            clipboard = event.text if event is not None else ''
        from backend.cli.terminal_sanitize import sanitize_prompt_input_text

        clipboard = sanitize_prompt_input_text(clipboard)
        if not clipboard:
            return
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    async def _on_paste(self, event: events.Paste) -> None:
        """Paste text or attach a clipboard image when available."""
        if self.read_only:
            return
        if await self._try_attach_clipboard_image():
            event.prevent_default()
            event.stop()
            return
        event.prevent_default()
        from backend.cli.terminal_sanitize import sanitize_prompt_input_text

        pasted = sanitize_prompt_input_text(event.text or '')
        if not pasted:
            event.stop()
            return
        if pasted != event.text:
            if result := self._replace_via_keyboard(pasted, *self.selection):
                self.move_cursor(result.end_location)
            event.stop()
            return
        self._paste_text_from_clipboard(event)

    async def action_paste(self) -> None:
        """Paste from system clipboard directly."""
        if self.read_only:
            return
        if await self._try_attach_clipboard_image():
            return
        try:
            pyperclip.paste()
        except Exception:
            return super().action_paste()
        self._paste_text_from_clipboard()

    def on_key(self, event: events.Key) -> None:
        if (
            event.key in {'backspace', 'delete'}
            and self._try_remove_pending_image_attachment()
        ):
            event.prevent_default()
            event.stop()
            return
        screen = getattr(self, 'screen', None)
        if event.key in {'pageup', 'pagedown'} and screen is not None:
            if event.key == 'pageup' and hasattr(screen, 'action_scroll_up'):
                screen.action_scroll_up()
            elif event.key == 'pagedown' and hasattr(screen, 'action_scroll_down'):
                screen.action_scroll_down()
            event.prevent_default()
            event.stop()
            return
        if event.key in {'up', 'down'} and bool(screen) and not self.text.strip():
            if getattr(screen, '_welcome_visible', False):
                if event.key == 'up' and hasattr(screen, 'action_focus_prev_card'):
                    screen.action_focus_prev_card()
                elif event.key == 'down' and hasattr(screen, 'action_focus_next_card'):
                    screen.action_focus_next_card()
                event.prevent_default()
                event.stop()
                return
            if hasattr(
                screen, '_handle_communicate_navigation'
            ) and screen._handle_communicate_navigation(event.key):
                event.prevent_default()
                event.stop()
                return
