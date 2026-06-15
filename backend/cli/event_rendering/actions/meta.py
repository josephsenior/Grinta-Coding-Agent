"""Action renderers — meta domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object

from rich.console import Group
from rich.text import Text

from backend.cli._typing import ActionRenderersHost
from backend.cli.display.transcript import (  # noqa: E402
    format_callout_panel,
)
from backend.cli.event_rendering.delegate import (
    summarize_delegate_action as _summarize_delegate_action,
)
from backend.cli.layout_tokens import (
    ACTIVITY_CARD_TITLE_DELEGATION,
    DECISION_PANEL_ACCENT_STYLE,
)
from backend.cli.theme import (
    CLR_OPTION_RECOMMENDED,
    CLR_OPTION_TEXT,
    CLR_QUESTION_TEXT,
    MARK_INFO,
    STYLE_DIM,
)
from backend.ledger.action import (  # noqa: E402
    ClarificationRequestAction,
    CondensationAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    ProposalAction,
    TaskTrackingAction,
    UncertaintyAction,
)


class _ActionMetaMixin(_ActionRenderersBase):
    def _render_task_tracking_action(self, action: TaskTrackingAction) -> None:
        command = str(getattr(action, 'command', '') or '').strip().lower()
        task_list = getattr(action, 'task_list', None)
        if command == 'update' and isinstance(task_list, list):
            self._set_task_panel(task_list)
        self.refresh()

    def _render_condensation_action(self, action: CondensationAction) -> None:
        count = getattr(self, '_condensation_count', 0) + 1
        self._condensation_count = count
        suffix = self._ordinal_suffix(count)

        self._ensure_reasoning()
        self._reasoning.update_action(f'Compressing context ({count}{suffix})…')

        host = getattr(self, '_host', None)
        if host is not None:
            host._hud.update_condensation_count(count)
        self.refresh()

    @staticmethod
    def _ordinal_suffix(n: int) -> str:
        if n % 10 == 1 and n % 11 != 1:
            return 'st'
        if n % 10 == 2 and n % 11 != 2:
            return 'nd'
        if n % 10 == 3 and n % 11 != 3:
            return 'rd'
        return 'th'

    def _render_delegate_task_action(self, action: DelegateTaskAction) -> None:
        self._flush_pending_tool_cards()
        self._reset_delegate_panel(batch_id=action.id if action.id > 0 else None)
        desc_display, secondary = _summarize_delegate_action(action)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_DELEGATION,
            verb='Delegated',
            detail=desc_display,
            secondary=secondary,
            kind='delegate',
            badge_label='workers',
        )
        self.refresh()

    def _render_escalate_to_human_action(self, action: EscalateToHumanAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        reason = getattr(action, 'reason', '')
        help_needed = getattr(action, 'specific_help_needed', '')
        escalate_parts: list[Any] = []
        if reason:
            escalate_parts.append(Text(reason, style=CLR_QUESTION_TEXT))
        if help_needed:
            escalate_parts.append(
                Text(f'Help needed: {help_needed}', style=CLR_QUESTION_TEXT)
            )
        if not escalate_parts:
            escalate_parts.append(
                Text('The agent needs your input to continue.', style=CLR_QUESTION_TEXT)
            )
        self._append_history(
            format_callout_panel(
                'Need Your Input',
                Group(*escalate_parts),
                accent_style=DECISION_PANEL_ACCENT_STYLE,
            )
        )
        self.refresh()

    def _render_clarification_request_action(
        self, action: ClarificationRequestAction
    ) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        question = getattr(action, 'question', '')
        options = getattr(action, 'options', []) or []
        clarify_parts: list[Any] = []
        if question:
            clarify_parts.append(Text(question, style=CLR_QUESTION_TEXT))
        for i, opt in enumerate(options, 1):
            option_line = Text()
            option_line.append(f'{i}. ', style=f'bold {CLR_OPTION_RECOMMENDED}')
            option_line.append(str(opt), style=CLR_OPTION_TEXT)
            clarify_parts.append(option_line)
        if clarify_parts:
            self._append_history(
                format_callout_panel(
                    'Question',
                    Group(*clarify_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()

    def _render_uncertainty_action(self, action: UncertaintyAction) -> None:
        self._flush_pending_tool_cards()
        concerns = getattr(action, 'specific_concerns', []) or []
        info_needed = getattr(action, 'requested_information', '')
        uncertainty_parts: list[Any] = []
        for concern in concerns[:5]:
            concern_line = Text()
            concern_line.append(f'{MARK_INFO} ', style=STYLE_DIM)
            concern_line.append(str(concern), style=STYLE_DIM)
            uncertainty_parts.append(concern_line)
        if info_needed:
            uncertainty_parts.append(
                Text(f'Need: {info_needed}', style=CLR_QUESTION_TEXT)
            )
        if uncertainty_parts:
            self._append_history(
                format_callout_panel(
                    'Needs Context',
                    Group(*uncertainty_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()

    def _render_proposal_action(self, action: ProposalAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        options = getattr(action, 'options', []) or []
        recommended = getattr(action, 'recommended', 0)
        rationale = getattr(action, 'rationale', '')
        proposal_parts: list[Any] = []
        if rationale:
            proposal_parts.append(Text(rationale, style=STYLE_DIM))
        for i, opt in enumerate(options):
            label = opt.get('name', opt.get('title', f'Option {i + 1}'))
            desc = opt.get('description', '')
            marker = ' (recommended)' if i == recommended else ''
            proposal_line = Text()
            proposal_line.append(
                f'{i + 1}. ',
                style=f'bold {DECISION_PANEL_ACCENT_STYLE}',
            )
            proposal_line.append(
                f'{label}{marker}',
                style=f'bold {CLR_OPTION_RECOMMENDED}'
                if i == recommended
                else f'bold {CLR_OPTION_TEXT}',
            )
            proposal_parts.append(proposal_line)
            if desc:
                proposal_parts.append(Text(f'   {desc}', style=STYLE_DIM))
        if proposal_parts:
            self._append_history(
                format_callout_panel(
                    'Options',
                    Group(*proposal_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()
