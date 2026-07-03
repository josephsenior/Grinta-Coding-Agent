"""AcceptanceCriteriaDetailScreen — bulleted criteria list for scan-line expand."""

from __future__ import annotations

from typing import Any

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    format_criterion_line,
    format_meta_chips,
    list_row_bullet,
)
from backend.cli.tui.transcript_typography import TX_BODY, TX_MUTED


_CRITERIA_VERBS: dict[str, str] = {
    'view': 'Viewed',
    'update': 'Defined',
    'append': 'Updated',
    'audit': 'Audited',
}


class AcceptanceCriteriaDetailScreen(DetailScreen):
    """Detail view for acceptance_criteria tool calls."""

    def __init__(
        self,
        *,
        command: str = 'view',
        criteria_list: list[dict[str, Any]] | None = None,
        status_message: str = '',
        fallback_body: str = '',
        title: str = '',
        kind: str = 'Criteria',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        command_key = str(command or 'view').strip().lower()
        verb = _CRITERIA_VERBS.get(command_key, 'Criteria')
        count = len(criteria_list or [])
        resolved_heading = heading or (
            f'{count} criterion' if count == 1 else f'{count} criteria'
            if count
            else verb
        )
        super().__init__(
            title=title or f'{kind}  {resolved_heading}',
            kind=kind,
            heading=resolved_heading,
            accent=accent,
        )
        self._command = command_key
        self._criteria_list = list(criteria_list or [])
        self._status_message = (status_message or '').strip()
        self._fallback_body = (fallback_body or '').strip()

    def build_content(self) -> list:
        widgets: list = []

        meta_parts: list[str] = []
        verb = _CRITERIA_VERBS.get(self._command, self._command or 'view')
        meta_parts.append(f'[{TX_MUTED}]{verb}[/]')
        if self._criteria_list:
            meta_parts.append(
                f'[{TX_MUTED}]{len(self._criteria_list)} item'
                f'{"s" if len(self._criteria_list) != 1 else ""}[/]'
            )
        if meta_parts:
            widgets.append(
                self.meta_row(
                    format_meta_chips(meta_parts),
                    widget_id='criteria-meta',
                )
            )

        if self._status_message:
            widgets.append(
                self.meta_row(
                    f'[{TX_BODY}]{self._status_message}[/]',
                    widget_id='criteria-status',
                )
            )

        rows = [
            format_criterion_line(item)
            for item in self._criteria_list
            if format_criterion_line(item)
        ]
        if rows:
            widgets.extend(
                self.section(
                    f'Criteria ({len(rows)})',
                    *[
                        self.list_row(list_row_bullet(line))
                        for line in rows
                    ],
                )
            )
        elif self._fallback_body:
            widgets.extend(
                self.section(
                    'Content',
                    self.code_block(self._fallback_body, widget_id='criteria-fallback'),
                )
            )
        elif not self._status_message:
            widgets.append(
                self.empty_state(
                    '(no criteria defined)',
                    widget_id='criteria-empty',
                )
            )

        return widgets
