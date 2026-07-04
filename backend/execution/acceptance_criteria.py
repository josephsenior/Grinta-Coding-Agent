"""Mixin for handling acceptance-criteria actions (update / view / append / refine / audit)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.core.criteria.evidence_ref import (
    EvidenceRefError,
    collect_session_events,
    resolve_evidence_ref,
)
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

    def _handle_criteria_view_action(
        self, action: AcceptanceCriteriaAction, criteria_file_path: str
    ) -> Observation:
        hydrated = list(getattr(action, 'criteria_list', []) or [])
        try:
            assert self.event_stream is not None
            content = self.event_stream.file_store.read(criteria_file_path)
            return AcceptanceCriteriaObservation(
                content=content,
                command=action.command,
                criteria_list=hydrated,
            )
        except FileNotFoundError:
            return AcceptanceCriteriaObservation(
                command=action.command,
                criteria_list=hydrated,
                content=(
                    'No acceptance criteria yet. Use `update` to define assertions.'
                ),
            )
        except Exception as e:
            return AcceptanceCriteriaObservation(
                command=action.command,
                criteria_list=hydrated,
                content=(
                    f'Failed to read acceptance criteria from {criteria_file_path}. Error: {e!s}'
                ),
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

        criteria_list = list(action.criteria_list)
        if action.command == 'audit' and action.audit_entries:
            try:
                criteria_list = self._apply_audit_entries(action)
            except EvidenceRefError as e:
                return ErrorObservation(str(e))

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

        n = len(criteria_list)
        if action.command == 'update':
            msg = (
                f'✅ Acceptance criteria defined ({n} items). '
                'Next: `task_tracker(update, ...)` if enabled, then begin implementation.'
            )
        elif action.command == 'append':
            msg = f'✅ Acceptance criteria updated ({n} total).'
        else:
            msg = f'✅ Acceptance criteria audit recorded for {n} item(s).'

        return AcceptanceCriteriaObservation(
            content=msg,
            command=action.command,
            criteria_list=criteria_list,
        )

    def _apply_audit_entries(
        self, action: AcceptanceCriteriaAction
    ) -> list[dict[str, Any]]:
        events = collect_session_events(self.event_stream)
        by_id = {
            str(item.get('id') or '').strip(): dict(item)
            for item in action.criteria_list
            if str(item.get('id') or '').strip()
        }
        for entry in action.audit_entries:
            criterion_id = str(entry.get('criterion_id') or '').strip()
            row = by_id.get(criterion_id)
            if row is None:
                msg = f'Audit entry references unknown criterion_id {criterion_id!r}'
                raise EvidenceRefError(msg)

            evidence_ref = str(entry.get('evidence_ref') or '').strip()
            if evidence_ref:
                resolved = resolve_evidence_ref(evidence_ref, events)
                row['evidence_ref'] = evidence_ref
                row['evidence'] = resolved
                continue

            evidence = str(entry.get('evidence') or '').strip()
            if not evidence:
                msg = (
                    f'Audit entry for {criterion_id!r} requires evidence_ref or '
                    'evidence with unverifiable=true.'
                )
                raise EvidenceRefError(msg)
            row['evidence'] = evidence
            row['evidence_ref'] = None

        missing = [
            criterion_id
            for criterion_id, row in by_id.items()
            if not str(row.get('evidence') or '').strip()
        ]
        if missing:
            raise EvidenceRefError(
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
            if not isinstance(item, dict):
                raise ValueError(f'Criterion {i} must be a dictionary')
            assertion = str(item.get('assertion') or '').strip()
            if not assertion:
                raise ValueError(f'Criterion {i} is missing assertion')
            source = str(item.get('source') or 'stated').strip().lower()
            evidence = str(item.get('evidence') or '').strip()
            criterion_id = str(item.get('id') or '').strip()
            id_prefix = f'[{criterion_id}] ' if criterion_id else ''
            line = f'{i}. {id_prefix}({source}) {assertion}'
            if evidence:
                line += f' — {evidence}'
            content += line + '\n'
            changes = item.get('changes')
            if isinstance(changes, list):
                for change in changes:
                    if not isinstance(change, dict):
                        continue
                    reason = str(change.get('reason') or '').strip()
                    old_assertion = str(change.get('old_assertion') or '').strip()
                    new_assertion = str(change.get('new_assertion') or '').strip()
                    if reason and old_assertion and new_assertion:
                        content += (
                            f'   - refined: "{old_assertion}" → "{new_assertion}" '
                            f'({reason})\n'
                        )
        return content
