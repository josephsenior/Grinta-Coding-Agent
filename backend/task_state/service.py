"""Task-state commands, validation, and deterministic review rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import (
    ContractItem,
    Evidence,
    TaskContract,
    TaskPlan,
    TaskState,
    TrackedTask,
)
from .store import TaskStateStore

_TASK_STATUSES = {'todo', 'in_progress', 'done', 'skipped', 'blocked'}
_CONTRACT_STATUSES = {'unknown', 'satisfied', 'gap', 'not_applicable'}
_SOURCES = {'user', 'repository', 'system', 'agent'}

_ACTION_FIELDS = {
    'set': {
        'action',
        'expected_revision',
        'objective',
        'requirements',
        'constraints',
        'success_conditions',
        'tasks',
    },
    'update_task': {
        'action',
        'expected_revision',
        'task_id',
        'status',
        'result',
    },
    'review': {'action', 'expected_revision'},
    'audit': {'action', 'expected_revision', 'evidence'},
}


def _contract_item_line(item: ContractItem) -> str:
    if item.status == 'satisfied':
        marker = '[ok]'
    elif item.status == 'gap':
        marker = '[gap]'
    else:
        marker = '[ ]'
    return f'{marker} {item.id} {item.text}'


def _plan_task_line(task: TrackedTask) -> str:
    if task.status == 'done':
        marker = '[done]'
    elif task.status == 'in_progress':
        marker = '[active]'
    else:
        marker = '[ ]'
    return f'{marker} {task.id} {task.description}'


def _contract_review_lines(contract: TaskContract) -> list[str]:
    lines = ['', 'OBJECTIVE', contract.objective or '(not recorded)']
    for heading, items in [
        ('REQUIREMENTS', contract.requirements),
        ('CONSTRAINTS', contract.constraints),
        ('SUCCESS CONDITIONS', contract.success_conditions),
    ]:
        lines.append('')
        lines.append(heading)
        lines += [_contract_item_line(item) for item in items] or ['(none)']
    return lines


def _plan_review_lines(plan: TaskPlan) -> list[str]:
    return ['', 'PLAN'] + [_plan_task_line(task) for task in plan.tasks]


def _recorded_status_lines(
    recorded_status: str,
    unresolved: list[str],
    actionable: list[str],
    blocked: list[str],
) -> list[str]:
    lines = ['', 'RECORDED STATUS']
    if recorded_status == 'active':
        details: list[str] = []
        if unresolved:
            details.append('unresolved contract: ' + ', '.join(unresolved))
        if actionable:
            details.append('open plan: ' + ', '.join(actionable))
        lines.append('ACTIVE — ' + '; '.join(details))
    elif recorded_status == 'blocked':
        lines.append('BLOCKED — ' + ', '.join(blocked))
    elif recorded_status == 'clear':
        lines.append('CLEAR — no unresolved contract conditions or open tasks recorded')
    else:
        lines.append('UNTRACKED — no durable contract or plan has been recorded')
    return lines


def _contract_groups(contract: TaskContract | None) -> list[list[ContractItem]]:
    if not contract:
        return []
    return [
        contract.requirements,
        contract.constraints,
        contract.success_conditions,
    ]


def _unresolved_contract_ids(contract: TaskContract | None) -> list[str]:
    return [
        item.id
        for group in _contract_groups(contract)
        for item in group
        if item.status in {'unknown', 'gap'}
    ]


def _task_ids_with_status(tasks: list[TrackedTask], statuses: set[str]) -> list[str]:
    return [task.id for task in tasks if task.status in statuses]


class TaskStateService:
    def __init__(self, store: TaskStateStore | None = None):
        self.store = store or TaskStateStore()

    def apply(self, action: str, arguments: dict[str, Any]) -> tuple[TaskState, str]:
        self._validate_action_fields(action, arguments)
        state = self.store.load()
        expected = arguments.get('expected_revision')
        if expected is not None and int(expected) != state.revision:
            raise ValueError(
                f'Task state changed since your last review. Current revision: {state.revision}.'
            )
        if action == 'review':
            return state, self.render_review(state)
        if action == 'set':
            self._set(state, arguments)
        elif action == 'update_task':
            self._update_task(state, arguments)
        elif action == 'audit':
            self._audit(state, arguments)
        else:
            raise ValueError(f'Unsupported task_state action {action!r}.')
        state.revision += 1
        state.updated_at = datetime.now(UTC).isoformat()
        self.store.save(state)
        return state, self.render_review(state)

    @staticmethod
    def _validate_action_fields(action: str, arguments: dict[str, Any]) -> None:
        allowed = _ACTION_FIELDS.get(action)
        if allowed is None:
            raise ValueError(f'Unsupported task_state action {action!r}.')
        unknown = sorted(set(arguments) - allowed)
        if not unknown:
            return
        fields = ', '.join(unknown)
        if action == 'set' and any(name in {'contract', 'plan'} for name in unknown):
            raise ValueError(
                f'Unsupported task_state(set) wrapper field(s): {fields}. '
                'Pass objective, requirements, constraints, success_conditions, '
                'and tasks as structured fields, not JSON strings.'
            )
        raise ValueError(f'Unsupported field(s) for task_state({action}): {fields}.')

    def _set(self, state: TaskState, args: dict[str, Any]) -> None:
        supplied_contract = any(
            k in args
            for k in ('objective', 'requirements', 'constraints', 'success_conditions')
        )
        if supplied_contract and state.contract is None:
            state.contract = TaskContract()
        if state.contract:
            if 'objective' in args:
                state.contract.objective = str(args['objective']).strip()
            for key in ('requirements', 'constraints', 'success_conditions'):
                if key in args:
                    setattr(state.contract, key, self._items(args[key], key[:3]))
        if 'tasks' in args:
            state.plan = TaskPlan(self._tasks(args['tasks']))

    def _items(self, rows: Any, prefix: str) -> list[ContractItem]:
        if not isinstance(rows, list):
            raise ValueError('Contract item fields must be lists.')
        result = []
        for n, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not str(row.get('text', '')).strip():
                raise ValueError('Each contract item needs text.')
            source = str(row.get('source', 'agent')).lower()
            if source not in _SOURCES:
                raise ValueError(f'Invalid requirement source {source!r}.')
            status = str(row.get('status', 'unknown')).lower()
            if status not in _CONTRACT_STATUSES:
                raise ValueError(
                    f'Invalid contract status {status!r} for item '
                    f'{str(row.get("id") or n)!r}. Expected one of: '
                    + ', '.join(sorted(_CONTRACT_STATUSES))
                    + '.'
                )
            result.append(
                ContractItem(
                    id=str(row.get('id') or f'{prefix}-{n}'),
                    text=str(row['text']).strip(),
                    source=source,
                    status=status,
                )
            )
        return result

    def _tasks(self, rows: Any) -> list[TrackedTask]:
        if not isinstance(rows, list):
            raise ValueError('tasks must be a list.')
        tasks = [
            TrackedTask(
                id=str(r.get('id', '')).strip(),
                description=str(r.get('description', '')).strip(),
                status=str(r.get('status', 'todo')),
                result=str(r.get('result', '')),
            )
            for r in rows
            if isinstance(r, dict)
        ]
        if any(
            not task.id or not task.description or task.status not in _TASK_STATUSES
            for task in tasks
        ):
            raise ValueError('Every task needs id, description, and a valid status.')
        return tasks

    def _update_task(self, state: TaskState, args: dict[str, Any]) -> None:
        if not state.plan:
            raise ValueError('No plan exists. Use task_state(set, tasks=[...]) first.')
        task_id, status = str(args.get('task_id', '')), str(args.get('status', ''))
        if status not in _TASK_STATUSES:
            raise ValueError(f'Invalid task status {status!r}.')
        for task in state.plan.tasks:
            if task.id == task_id:
                task.status = status
                if 'result' in args:
                    task.result = str(args['result'])
                return
        raise ValueError(f'Task {task_id!r} not found.')

    @staticmethod
    def _audit_items_by_id(contract: TaskContract) -> dict[str, ContractItem]:
        all_items = (
            contract.requirements + contract.constraints + contract.success_conditions
        )
        return {item.id: item for item in all_items}

    @staticmethod
    def _audit_evidence_rows(args: dict[str, Any]) -> list[Any]:
        rows = args.get('evidence', [])
        if not isinstance(rows, list):
            raise ValueError('Audit evidence must be a list.')
        return rows

    @staticmethod
    def _validate_audit_source_event_ids(source_event_ids: Any) -> None:
        if not isinstance(source_event_ids, list):
            raise ValueError(
                'source_event_ids must be a list of non-negative integers.'
            )
        if len(source_event_ids) > 50 or any(
            not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 0
            for event_id in source_event_ids
        ):
            raise ValueError(
                'source_event_ids must contain at most 50 non-negative integers.'
            )

    @classmethod
    def _apply_audit_evidence_row(
        cls,
        by_id: dict[str, ContractItem],
        row: Any,
    ) -> None:
        if not isinstance(row, dict):
            raise ValueError('Audit entries must be objects.')
        item = by_id.get(str(row.get('item_id', '')))
        status = str(row.get('status', ''))
        if item is None or status not in _CONTRACT_STATUSES:
            raise ValueError('Audit entries need known item_id and valid status.')
        item.status = status
        source_event_ids = row.get('source_event_ids', [])
        cls._validate_audit_source_event_ids(source_event_ids)
        item.evidence.append(
            Evidence(
                kind=str(row.get('kind', 'inspection')),
                summary=str(row.get('evidence', '')).strip(),
                source_event_ids=list(dict.fromkeys(source_event_ids)),
            )
        )

    def _audit(self, state: TaskState, args: dict[str, Any]) -> None:
        if not state.contract:
            raise ValueError('No contract exists. Use task_state(set) first.')
        by_id = self._audit_items_by_id(state.contract)
        for row in self._audit_evidence_rows(args):
            self._apply_audit_evidence_row(by_id, row)

    def render_review(self, state: TaskState) -> str:
        lines = [f'TASK STATE (revision {state.revision})']
        if state.contract:
            lines += _contract_review_lines(state.contract)
        if state.plan:
            lines += _plan_review_lines(state.plan)
        lines += _recorded_status_lines(*self.recorded_status(state))
        return '\n'.join(lines)

    @staticmethod
    def recorded_status(
        state: TaskState,
    ) -> tuple[str, list[str], list[str], list[str]]:
        """Summarize recorded state without making a completion decision.

        ``CLEAR`` means only that the recorded state has no unresolved contract
        items or open plan work. The model still owns the decision to finish.
        """
        unresolved = _unresolved_contract_ids(state.contract)
        tasks = state.plan.tasks if state.plan else []
        actionable = _task_ids_with_status(tasks, {'todo', 'in_progress'})
        blocked = _task_ids_with_status(tasks, {'blocked'})
        if unresolved or actionable:
            return 'active', unresolved, actionable, blocked
        if blocked:
            return 'blocked', unresolved, actionable, blocked
        if state.contract is not None or state.plan is not None:
            return 'clear', unresolved, actionable, blocked
        return 'untracked', unresolved, actionable, blocked
