"""Task-state aggregate and JSON conversion helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Evidence:
    kind: str
    summary: str
    source_event_ids: list[int] = field(default_factory=list)
    created_at: str = field(default_factory=_now)


@dataclass
class ContractItem:
    id: str
    text: str
    source: str = 'agent'
    status: str = 'unknown'
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class TaskContract:
    objective: str = ''
    requirements: list[ContractItem] = field(default_factory=list)
    constraints: list[ContractItem] = field(default_factory=list)
    success_conditions: list[ContractItem] = field(default_factory=list)


@dataclass
class TrackedTask:
    id: str
    description: str
    status: str = 'todo'
    result: str = ''


@dataclass
class TaskPlan:
    tasks: list[TrackedTask] = field(default_factory=list)


@dataclass
class TaskState:
    version: int = 1
    revision: int = 0
    contract: TaskContract | None = None
    plan: TaskPlan | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> 'TaskState':
        def items(value: Any) -> list[ContractItem]:
            return (
                [
                    ContractItem(
                        id=str(row.get('id', '')).strip(),
                        text=str(row.get('text', '')).strip(),
                        source=str(row.get('source', 'agent')).strip(),
                        status=str(row.get('status', 'unknown')).strip(),
                        evidence=[
                            Evidence(**e)
                            for e in row.get('evidence', [])
                            if isinstance(e, dict)
                        ],
                    )
                    for row in value
                    if isinstance(row, dict)
                ]
                if isinstance(value, list)
                else []
            )

        contract_raw = raw.get('contract')
        contract = None
        if isinstance(contract_raw, dict):
            contract = TaskContract(
                objective=str(contract_raw.get('objective', '')).strip(),
                requirements=items(contract_raw.get('requirements')),
                constraints=items(contract_raw.get('constraints')),
                success_conditions=items(contract_raw.get('success_conditions')),
            )
        plan_raw = raw.get('plan')
        plan = None
        if isinstance(plan_raw, dict):
            plan = TaskPlan(
                [
                    TrackedTask(
                        **{
                            k: str(row.get(k, ''))
                            for k in ('id', 'description', 'status', 'result')
                        }
                    )
                    for row in plan_raw.get('tasks', [])
                    if isinstance(row, dict)
                ]
            )
        return cls(
            version=int(raw.get('version', 1)),
            revision=int(raw.get('revision', 0)),
            contract=contract,
            plan=plan,
            created_at=str(raw.get('created_at') or _now()),
            updated_at=str(raw.get('updated_at') or _now()),
        )
