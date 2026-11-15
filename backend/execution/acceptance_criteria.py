"""Mixin for handling acceptance-criteria actions (update / view / append / refine / audit)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.ledger.observation import (
    AcceptanceCriteriaObservation,
    ErrorObservation,
    NullObservation,
    Observation,
)
from backend.persistence.locations import get_conversation_dir

logger = logging.getLogger(__name__)

_CRITERIA_NOOP_PREFIX = (
    '[ACCEPTANCE_CRITERIA] Update skipped because the criteria list is unchanged.'
)

if TYPE_CHECKING:
    from backend.ledger.action import AcceptanceCriteriaAction


class AcceptanceCriteriaMixin:
    """Mixin that adds acceptance-criteria capabilities to a Runtime."""

    if TYPE_CHECKING:
        sid: str
        event_stream: Any

    def _handle_acceptance_criteria_action(
        self, action: AcceptanceCriteriaAction
    ) -> Observation:
        """Handle acceptance criteria actions."""
        if self.event_stream is None:
            return ErrorObservation('Acceptance criteria requires an event stream')

        conversation_dir = get_conversation_dir(self.sid, self.event_stream.user_id)
        criteria_file_path = f'{conversation_dir}CRITERIA.md'

        if action.command == 'view':
            return self._handle_criteria_view_action(action, criteria_file_path)
        if action.command == 'refine':
            return self._handle_criteria_refine_action(action, criteria_file_path)
        if action.command in {'update', 'append', 'audit'}:
            return self._handle_criteria_write_action(action, criteria_file_path)
        return NullObservation('')

    def _load_criteria_for_view(
        self, action: AcceptanceCriteriaAction
    ) -> list[dict[str, Any]]:
        """Load structured criteria from JSON store, falling back to hydrated action."""
        try:
            from backend.core.criteria.acceptance_criteria_store import (
                AcceptanceCriteriaStore,
            )

            stored = AcceptanceCriteriaStore().load_from_file()
            if stored:
                return stored
        except Exception:
            logger.debug('Failed to load criteria from JSON store', exc_info=True)
        return list(getattr(action, 'criteria_list', []) or [])

    def _sync_criteria_markdown_cache(
        self, criteria_file_path: str, content: str
    ) -> None:
        """Keep CRITERIA.md aligned with JSON-derived markdown."""
        try:
            assert self.event_stream is not None
            self.event_stream.file_store.write(criteria_file_path, content)
        except Exception:
            logger.debug('Failed to sync CRITERIA.md cache', exc_info=True)

    def _handle_criteria_view_action(
        self, action: AcceptanceCriteriaAction, criteria_file_path: str
    ) -> Observation:
        criteria_list = self._load_criteria_for_view(action)
        if not criteria_list:
            return AcceptanceCriteriaObservation(
                command=action.command,
                criteria_list=[],
                content=(
                    'No acceptance criteria yet. Use `update` to define assertions.'
                ),
            )
        try:
            content = self._generate_criteria_markdown(criteria_list)
        except ValueError as e:
            return AcceptanceCriteriaObservation(
                command=action.command,
                criteria_list=criteria_list,
                content=f'Invalid criteria list: {e!s}',
            )
        self._sync_criteria_markdown_cache(criteria_file_path, content)
        return AcceptanceCriteriaObservation(
            content=content,
            command=action.command,
            criteria_list=criteria_list,
        )

    def _handle_criteria_refine_action(
        self, action: AcceptanceCriteriaAction, criteria_file_path: str
    ) -> Observation:
        from backend.core.criteria.acceptance_criteria_store import (
            AcceptanceCriteriaStore,
            build_refined_criteria_list,
        )

        store = AcceptanceCriteriaStore()
        try:
            updated = build_refined_criteria_list(
                store.load_from_file(),
                criterion_id=action.criterion_id,
                new_assertion=action.new_assertion,
                reason=action.reason,
                changed_at=datetime.now(UTC).isoformat(),
            )
        except KeyError:
            return ErrorObservation(
                f'Criterion {action.criterion_id!r} not found. Call view for current ids.'
            )
        except ValueError as e:
            return ErrorObservation(f'Invalid refine request: {e!s}')

        persist_action = replace(action, criteria_list=updated)
        try:
            content = self._generate_criteria_markdown(updated)
        except ValueError as e:
            return ErrorObservation(f'Invalid criteria list: {e!s}')

        persist_error = self._persist_criteria(
            persist_action, criteria_file_path, content=content
        )
        if persist_error is not None:
            return persist_error

        msg = (
            f'✅ Criterion {action.criterion_id} refined. '
            f'Reason recorded: {action.reason.strip()}'
        )
        return AcceptanceCriteriaObservation(
            content=msg,
            command='refine',
            criteria_list=updated,
        )

    def _handle_criteria_write_action(
        self, action: AcceptanceCriteriaAction, criteria_file_path: str
    ) -> Observation:
        thought = (getattr(action, 'thought', '') or '').strip()
        if thought.startswith(_CRITERIA_NOOP_PREFIX):
            return AcceptanceCriteriaObservation(
                content=thought,
                command=action.command,
                criteria_list=action.criteria_list,
            )

        criteria_list, audit_error = self._resolve_criteria_write_list(action)
        if audit_error is not None:
            return audit_error

        try:
            content = self._generate_criteria_markdown(criteria_list)
        except ValueError as e:
            return ErrorObservation(f'Invalid criteria list: {e!s}')

        persist_action = replace(action, criteria_list=criteria_list)
        persist_error = self._persist_criteria(
            persist_action, criteria_file_path, content=content
        )
        if persist_error is not None:
            return persist_error

        return AcceptanceCriteriaObservation(
            content=self._criteria_write_message(action.command, len(criteria_list)),
            command=action.command,
            criteria_list=criteria_list,
        )

    def _resolve_criteria_write_list(
        self, action: AcceptanceCriteriaAction
    ) -> tuple[list[dict[str, Any]], ErrorObservation | None]:
        criteria_list = list(action.criteria_list)
        if action.command != 'audit' or not action.audit_entries:
            return criteria_list, None
        try:
            return self._apply_audit_entries(action), None
        except ValueError as e:
            return criteria_list, ErrorObservation(str(e))
        except Exception as e:
            logger.warning('Acceptance criteria audit failed', exc_info=True)
            return criteria_list, ErrorObservation(
                f'Acceptance criteria audit failed: {e!s}'
            )

    @staticmethod
    def _criteria_write_message(command: str, count: int) -> str:
        if command == 'update':
            return (
                f'✅ Acceptance criteria defined ({count} items). '
                'Next: `task_tracker(update, ...)` if enabled, then begin implementation.'
            )
        if command == 'append':
            return f'✅ Acceptance criteria updated ({count} total).'
        return f'✅ Acceptance criteria audit recorded for {count} item(s).'

    @staticmethod
    def _criteria_by_id(criteria_list: list) -> dict[str, dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for item in criteria_list:
            criterion_id = str(item.get('id') or '').strip()
            if criterion_id:
                by_id[criterion_id] = dict(item)
        return by_id

    @staticmethod
    def _apply_audit_entry(
        by_id: dict[str, dict[str, Any]], entry: dict[str, Any]
    ) -> None:
        criterion_id = str(entry.get('criterion_id') or '').strip()
        row = by_id.get(criterion_id)
        if row is None:
            msg = f'Audit entry references unknown criterion_id {criterion_id!r}'
            raise ValueError(msg)

        evidence = str(entry.get('evidence') or '').strip()
        if not evidence:
            msg = f'Audit entry for {criterion_id!r} requires non-empty evidence.'
            raise ValueError(msg)
        row['evidence'] = evidence

    @staticmethod
    def _missing_audit_evidence(by_id: dict[str, dict[str, Any]]) -> list[str]:
        return [
            criterion_id
            for criterion_id, row in by_id.items()
            if not str(row.get('evidence') or '').strip()
        ]

    def _apply_audit_entries(
        self, action: AcceptanceCriteriaAction
    ) -> list[dict[str, Any]]:
        by_id = self._criteria_by_id(action.criteria_list)
        for entry in action.audit_entries:
            self._apply_audit_entry(by_id, entry)

        missing = self._missing_audit_evidence(by_id)
        if missing:
            raise ValueError(
                f'Audit incomplete; missing evidence for: {", ".join(sorted(missing))}'
            )
        return list(by_id.values())

    def _persist_criteria(
        self,
        action: AcceptanceCriteriaAction,
        criteria_file_path: str,
        *,
        content: str,
    ) -> ErrorObservation | None:
        """Write CRITERIA.md and acceptance_criteria.json; roll back markdown on JSON failure."""
        try:
            assert self.event_stream is not None
            self.event_stream.file_store.write(criteria_file_path, content)
        except Exception as e:
            return ErrorObservation(
                f'Failed to write acceptance criteria to {criteria_file_path}: {e!s}'
            )

        try:
            from backend.core.criteria.acceptance_criteria_store import (
                AcceptanceCriteriaStore,
            )

            AcceptanceCriteriaStore().save_to_file(list(action.criteria_list))
        except Exception as e:
            try:
                self.event_stream.file_store.delete(criteria_file_path)
            except Exception:
                pass
            return ErrorObservation(
                f'Failed to persist acceptance_criteria.json after CRITERIA.md write: {e!s}'
            )
        return None

    @staticmethod
    def _generate_criteria_markdown(criteria_list: list) -> str:
        """Generate markdown content for acceptance criteria."""
        if not criteria_list:
            return '# Acceptance Criteria\n\n_(none)_\n'

        content = '# Acceptance Criteria\n\n'
        for i, item in enumerate(criteria_list, 1):
            content += AcceptanceCriteriaMixin._criteria_item_markdown(i, item)
        return content

    @staticmethod
    def _criteria_item_markdown(index: int, item: Any) -> str:
        if not isinstance(item, dict):
            raise ValueError(f'Criterion {index} must be a dictionary')
        assertion = str(item.get('assertion') or '').strip()
        if not assertion:
            raise ValueError(f'Criterion {index} is missing assertion')
        source = str(item.get('source') or 'stated').strip().lower()
        evidence = str(item.get('evidence') or '').strip()
        criterion_id = str(item.get('id') or '').strip()
        id_prefix = f'[{criterion_id}] ' if criterion_id else ''
        line = f'{index}. {id_prefix}({source}) {assertion}'
        if evidence:
            line += f' — {evidence}'
        changes = AcceptanceCriteriaMixin._criteria_changes_markdown(
            item.get('changes')
        )
        return line + '\n' + changes

    @staticmethod
    def _criteria_changes_markdown(changes: Any) -> str:
        if not isinstance(changes, list):
            return ''
        content = ''
        for change in changes:
            if not isinstance(change, dict):
                continue
            reason = str(change.get('reason') or '').strip()
            old_assertion = str(change.get('old_assertion') or '').strip()
            new_assertion = str(change.get('new_assertion') or '').strip()
            if reason and old_assertion and new_assertion:
                content += (
                    f'   - refined: "{old_assertion}" → "{new_assertion}" ({reason})\n'
                )
        return content
