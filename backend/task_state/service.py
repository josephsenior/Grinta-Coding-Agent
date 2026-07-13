"""Task-state commands, validation, and deterministic review rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import ContractItem, Evidence, TaskContract, TaskPlan, TaskState, TrackedTask
from .store import TaskStateStore

_TASK_STATUSES = {'todo', 'in_progress', 'done', 'skipped', 'blocked'}
_CONTRACT_STATUSES = {'unknown', 'satisfied', 'gap', 'not_applicable'}
_SOURCES = {'user', 'repository', 'system', 'agent'}


class TaskStateService:
    def __init__(self, store: TaskStateStore | None = None): self.store = store or TaskStateStore()

    def apply(self, action: str, arguments: dict[str, Any]) -> tuple[TaskState, str]:
        state = self.store.load()
        expected = arguments.get('expected_revision')
        if expected is not None and int(expected) != state.revision:
            raise ValueError(f'Task state changed since your last review. Current revision: {state.revision}.')
        if action == 'review': return state, self.render_review(state)
        if action == 'set': self._set(state, arguments)
        elif action == 'update_task': self._update_task(state, arguments)
        elif action == 'audit': self._audit(state, arguments)
        else: raise ValueError(f'Unsupported task_state action {action!r}.')
        state.revision += 1; state.updated_at = datetime.now(UTC).isoformat(); self.store.save(state)
        return state, self.render_review(state)

    def _set(self, state: TaskState, args: dict[str, Any]) -> None:
        supplied_contract = any(k in args for k in ('objective', 'requirements', 'constraints', 'success_conditions'))
        if supplied_contract and state.contract is None: state.contract = TaskContract()
        if state.contract:
            if 'objective' in args: state.contract.objective = str(args['objective']).strip()
            for key in ('requirements', 'constraints', 'success_conditions'):
                if key in args: setattr(state.contract, key, self._items(args[key], key[:3]))
        if 'tasks' in args: state.plan = TaskPlan(self._tasks(args['tasks']))

    def _items(self, rows: Any, prefix: str) -> list[ContractItem]:
        if not isinstance(rows, list): raise ValueError('Contract item fields must be lists.')
        result = []
        for n, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not str(row.get('text', '')).strip(): raise ValueError('Each contract item needs text.')
            source = str(row.get('source', 'agent')).lower()
            if source not in _SOURCES: raise ValueError(f'Invalid requirement source {source!r}.')
            result.append(ContractItem(id=str(row.get('id') or f'{prefix}-{n}'), text=str(row['text']).strip(), source=source, status=str(row.get('status', 'unknown'))))
        return result

    def _tasks(self, rows: Any) -> list[TrackedTask]:
        if not isinstance(rows, list): raise ValueError('tasks must be a list.')
        tasks = [TrackedTask(id=str(r.get('id', '')).strip(), description=str(r.get('description', '')).strip(), status=str(r.get('status', 'todo')), result=str(r.get('result', ''))) for r in rows if isinstance(r, dict)]
        if any(not task.id or not task.description or task.status not in _TASK_STATUSES for task in tasks): raise ValueError('Every task needs id, description, and a valid status.')
        return tasks

    def _update_task(self, state: TaskState, args: dict[str, Any]) -> None:
        if not state.plan: raise ValueError('No plan exists. Use task_state(set, tasks=[...]) first.')
        task_id, status = str(args.get('task_id', '')), str(args.get('status', ''))
        if status not in _TASK_STATUSES: raise ValueError(f'Invalid task status {status!r}.')
        for task in state.plan.tasks:
            if task.id == task_id:
                task.status = status
                if 'result' in args: task.result = str(args['result'])
                return
        raise ValueError(f'Task {task_id!r} not found.')

    def _audit(self, state: TaskState, args: dict[str, Any]) -> None:
        if not state.contract: raise ValueError('No contract exists. Use task_state(set) first.')
        all_items = state.contract.requirements + state.contract.constraints + state.contract.success_conditions
        by_id = {item.id: item for item in all_items}
        for row in args.get('evidence', []):
            item = by_id.get(str(row.get('item_id', '')))
            status = str(row.get('status', ''))
            if item is None or status not in _CONTRACT_STATUSES: raise ValueError('Audit entries need known item_id and valid status.')
            item.status = status; item.evidence.append(Evidence(kind=str(row.get('kind', 'inspection')), summary=str(row.get('evidence', '')).strip()))

    def render_review(self, state: TaskState) -> str:
        lines = [f'TASK STATE (revision {state.revision})']
        if state.contract:
            lines += ['', 'OBJECTIVE', state.contract.objective or '(not recorded)']
            for heading, items in [('REQUIREMENTS', state.contract.requirements), ('CONSTRAINTS', state.contract.constraints), ('SUCCESS CONDITIONS', state.contract.success_conditions)]:
                lines.append(''); lines.append(heading)
                lines += [f"{'[ok]' if x.status == 'satisfied' else '[gap]' if x.status == 'gap' else '[ ]'} {x.id} {x.text}" for x in items] or ['(none)']
        if state.plan:
            lines += ['', 'PLAN'] + [f"{'[done]' if x.status == 'done' else '[active]' if x.status == 'in_progress' else '[ ]'} {x.id} {x.description}" for x in state.plan.tasks]
        unresolved = [x.id for group in ([state.contract.requirements, state.contract.constraints, state.contract.success_conditions] if state.contract else []) for x in group if x.status in {'unknown', 'gap'}]
        incomplete = [x.id for x in (state.plan.tasks if state.plan else []) if x.status in {'todo', 'in_progress', 'blocked'}]
        lines += ['', 'READINESS', 'READY' if not unresolved else 'Not ready: ' + ', '.join(unresolved)]
        if incomplete: lines.append('Plan still active: ' + ', '.join(incomplete))
        return '\n'.join(lines)
