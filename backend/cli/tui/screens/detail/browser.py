"""BrowserDetailScreen — full URL, action log, extracted content, links."""

from __future__ import annotations

from textual.widgets import Rule, Static

from backend.cli.tui.screens.detail.base import DetailScreen


class BrowserDetailScreen(DetailScreen):
    """Browser action detail: URL, action list, extracted content, links."""

    def __init__(
        self,
        full_url: str = '',
        actions: list[str] | None = None,
        extracted: str = '',
        links: list[str] | None = None,
        *,
        title: str = 'Browser',
    ) -> None:
        super().__init__(title=title)
        self._full_url = full_url
        self._actions = list(actions or [])
        self._extracted = extracted
        self._links = list(links or [])

    def build_content(self) -> list:
        widgets: list = []

        if self._full_url:
            widgets.append(
                Static(
                    f'[#91abec]{self._full_url}[/]',
                    id='browser-url',
                )
            )

        if self._actions:
            widgets.append(Rule('Actions', line_style='heavy'))
            for action in self._actions:
                widgets.append(
                    Static(
                        f'  [#c8d4e8]→[/] [#e2e8f0]{action}[/]',
                        classes='browser-action',
                    )
                )

        if self._extracted:
            widgets.append(Rule('Extracted', line_style='heavy'))
            widgets.append(Static(self._extracted, id='browser-extracted'))

        if self._links:
            link_header = f'Links ({len(self._links)})'
            widgets.append(Static(f'[#54597b]{link_header}[/]', id='browser-links-hdr'))
            for link in self._links:
                widgets.append(
                    Static(
                        f'  → [#91abec]{link}[/]',
                        classes='browser-link',
                    )
                )

        if not widgets:
            widgets.append(Static('(no browser data)', id='browser-empty'))

        return widgets
