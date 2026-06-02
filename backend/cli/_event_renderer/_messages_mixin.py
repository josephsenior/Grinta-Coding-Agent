"""Messages methods for CLIEventRenderer.

User/system message rendering & history (add_user/add_system/_append_history/_print_or_buffer).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli._event_renderer.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.panels import (
    build_system_notice_panel as _build_system_notice_panel,
)
from backend.cli._event_renderer.panels import (
    normalize_system_title as _normalize_system_title,
)
from backend.cli.layout_tokens import (
    CALLOUT_PANEL_PADDING,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
)
from backend.cli.status_chrome import rich_fake_prompt_group, status_fields_from_hud
from backend.cli.theme import (
    CLR_USER_BG,
    CLR_USER_BORDER,
    STYLE_BOLD_DIM,
    STYLE_DIM,
    get_grinta_pygments_style,
)

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)


class _EventRendererMessagesMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    async def add_user_message(self, text: str) -> None:
        """Print a user turn — rounded panel, high-contrast label."""
        body = Markdown((text or '').rstrip(), code_theme=get_grinta_pygments_style())
        panel = Panel(
            Padding(body, CALLOUT_PANEL_PADDING),
            title=Text('  You  ', style=STYLE_BOLD_DIM),
            title_align='left',
            box=box.ROUNDED,
            border_style=CLR_USER_BORDER,
            padding=(0, 0),
            style=CLR_USER_BG,
        )
        framed = frame_transcript_body(panel)
        group = Group(framed)

        if self._live is not None:
            # Same path as committed transcript lines during a turn: print into
            # scrollback while Live is active, then refresh so the layout stays
            # coherent (printing before Live started could be erased on refresh).
            self._console.print(group)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, 'app', None) if sess is not None else None
        if app is not None and getattr(app, 'is_running', False):
            await self._safe_print_above_prompt(group)
            return

        self._console.print(group)

    def add_system_message(self, text: str, *, title: str = 'Info') -> None:
        normalized_title = _normalize_system_title(title)
        lower_title = normalized_title.lower()
        if lower_title == 'error':
            use_notice = _use_recoverable_notice_style(text)
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title='Error',
                        force_notice=use_notice,
                        content_width=self._console.width,
                    )
                )
            )
            if use_notice:
                self._hud.update_ledger('Idle')
                self._hud.update_agent_state('Ready')
            else:
                self._hud.update_ledger('Error')
            return
        if 'timeout' in lower_title:
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title=normalized_title,
                        force_notice=True,
                        content_width=self._console.width,
                    )
                )
            )
            self._hud.update_ledger('Idle')
            self._hud.update_agent_state('Ready')
            return
        tone = 'warning' if lower_title == 'warning' else 'info'
        panel = _build_system_notice_panel(
            text,
            title=normalized_title,
            tone=tone,
        )
        self._print_or_buffer(frame_transcript_body(panel))

    def add_markdown_block(self, title: str, text: str) -> None:
        from rich.rule import Rule

        self._print_or_buffer(Text(''))
        self._print_or_buffer(
            Padding(Rule(title, style=STYLE_DIM), (1, 0, 1, 0), expand=False)
        )
        self._print_or_buffer(
            Padding(
                Markdown(text, code_theme=get_grinta_pygments_style()),
                (0, 0, 1, 0),
                expand=False,
            )
        )
        self._print_or_buffer(Text(''))

    def add_renderable(self, renderable: Any, *, force_terminal: bool = False) -> None:
        """Buffer or print a raw Rich renderable directly.

        When *force_terminal* is True (e.g. for Rich tables that need proper
        column sizing), the renderable is serialised to a temporary
        ``force_terminal=True`` console and delivered as a system message.
        """
        if not force_terminal:
            self._print_or_buffer(renderable)
            return

        from io import StringIO


        sio = StringIO()
        tc = Console(file=sio, force_terminal=True, width=100)
        tc.print(renderable)
        self.add_system_message(sio.getvalue().strip(), title='help')

    def _collect_live_sections(self) -> list[Any]:
        sections: list[Any] = []
        # Task panel moved to sidebar
        if self._delegate_panel is not None:
            sections.append(self._delegate_panel)
        return sections

    def _append_streaming_and_reasoning_sections(
        self,
        live_sections: list[Any],
        stream_max_lines: int | None,
        max_width: int,
    ) -> Any | None:
        reasoning_section: Any | None = None
        if self._reasoning.active:
            reasoning_section = self._reasoning.renderable(
                max_width=max_width,
                max_lines=None,
            )
            if reasoning_section is not None:
                live_sections.append(reasoning_section)

        return reasoning_section

    @staticmethod
    def _frame_live_sections(
        live_sections: list[Any],
    ) -> list[Any]:
        body_items: list[Any] = []
        for index, section in enumerate(live_sections):
            framed = frame_live_body(section)
            if index < len(live_sections) - 1:
                body_items.append(gap_below_live_section(framed))
            else:
                body_items.append(framed)
        return body_items

    def _render_fake_prompt(self, width: int) -> Any:
        """Render a prompt look-alike anchored at the bottom of the Live display.

        Visually matches the prompt_toolkit bottom_toolbar so the transition
        between Live (agent executing) and prompt_toolkit (user input) is
        seamless — the input area and stats bar never appear to disappear.
        """
        w = max(1, int(width or self._console.width or 80))
        fields = status_fields_from_hud(self._hud.state, self._hud.bundled_skill_count)
        return rich_fake_prompt_group(fields, w)

    def _append_history(self, renderable: Any) -> None:
        """Add a renderable: buffer during Live, print otherwise."""
        self._print_or_buffer(renderable)

    def _print_or_buffer(self, renderable: Any) -> None:
        """Print transcript output, or schedule above the prompt when idle with PT.

        While Rich ``Live`` is active (agent turn), print each committed line
        through the same console so it lands in normal scrollback and the Live
        region only holds streaming, reasoning, tasks, and HUD — avoiding
        terminal-height clipping.

        When a prompt_toolkit session is active (user at the input prompt), Rich
        ``console.print`` writes at the wrong cursor and corrupts the multiline
        prompt.  In that case schedule ``run_in_terminal`` so output scrolls above
        the prompt.
        """
        framed = frame_transcript_body(renderable)
        if self._live is not None:
            self._console.print(framed)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, 'app', None) if sess is not None else None
        if app is not None and getattr(app, 'is_running', False):
            try:
                task = self._loop.create_task(self._safe_print_above_prompt(framed))

                def _log_fail(t: asyncio.Task) -> None:
                    try:
                        t.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.debug(
                            'Safe console print above prompt failed',
                            exc_info=True,
                        )

                task.add_done_callback(_log_fail)
            except RuntimeError:
                self._console.print(framed)
            return

        self._console.print(framed)

    async def _safe_print_above_prompt(self, renderable: Any) -> None:
        from prompt_toolkit.application import run_in_terminal

        def _sync_print() -> None:
            self._console.print(renderable)

        await run_in_terminal(_sync_print)
