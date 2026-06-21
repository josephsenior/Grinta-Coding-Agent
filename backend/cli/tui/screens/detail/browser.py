"""BrowserDetailScreen — full URL, action log, extracted content, links."""

from __future__ import annotations

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
        kind: str = 'Browser',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        super().__init__(
            title=title,
            kind=kind,
            heading=heading,
            accent=accent,
        )
        self._full_url = full_url
        self._actions = list(actions or [])
        self._extracted = extracted
        self._links = list(links or [])

    def build_content(self) -> list:
        widgets: list = []

        if self._full_url:
            widgets.extend(
                self.section(
                    'URL',
                    self.meta_row(
                        f'[bold #91abec]{self._full_url}[/]',
                        widget_id='browser-url',
                    ),
                )
            )

        if self._actions:
            widgets.extend(
                self.section(
                    'Actions',
                    *[
                        self.list_row(f'[#c8d4e8]→[/] [#e2e8f0]{action}[/]')
                        for action in self._actions
                    ],
                )
            )

        if self._extracted:
            widgets.extend(
                self.section(
                    'Extracted',
                    self.code_block(self._extracted, widget_id='browser-extracted'),
                )
            )

        if self._links:
            widgets.extend(
                self.section(
                    f'Links ({len(self._links)})',
                    *[
                        self.list_row(f'→ [#91abec]{link}[/]')
                        for link in self._links
                    ],
                )
            )

        if not widgets:
            widgets.append(self.empty_state('(no browser data)', widget_id='browser-empty'))

        return widgets
