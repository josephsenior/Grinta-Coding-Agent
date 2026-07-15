import pytest

from backend.task_state.service import TaskStateService
from backend.task_state.store import TaskStateStore


def test_set_preserves_unsupplied_contract_fields(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    state, _ = service.apply(
        'set',
        {
            'objective': 'Ship it',
            'requirements': [{'id': 'req-1', 'text': 'Keep API', 'source': 'user'}],
        },
    )
    state, _ = service.apply(
        'set',
        {
            'tasks': [{'id': 'task-1', 'description': 'Inspect'}],
            'expected_revision': state.revision,
        },
    )
    assert state.contract is not None
    assert state.contract.requirements[0].text == 'Keep API'
    assert state.plan is not None


def test_audit_records_structured_evidence(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    service.apply('set', {'requirements': [{'id': 'req-1', 'text': 'Tests pass'}]})
    state, _ = service.apply(
        'audit',
        {
            'evidence': [
                {
                    'item_id': 'req-1',
                    'status': 'satisfied',
                    'kind': 'test',
                    'evidence': '12 passed',
                }
            ]
        },
    )
    item = state.contract.requirements[0]
    assert item.status == 'satisfied'
    assert item.evidence[0].kind == 'test'


def test_active_plan_never_renders_clear(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    _, review = service.apply(
        'set',
        {
            'tasks': [
                {'id': 'done', 'description': 'Finish milestone', 'status': 'done'},
                {
                    'id': 'next',
                    'description': 'Continue overall objective',
                    'status': 'todo',
                },
            ]
        },
    )

    assert 'RECORDED STATUS\nACTIVE' in review
    assert 'open plan: next' in review
    assert 'RECORDED STATUS\nCLEAR' not in review


def test_blocked_plan_is_reported_without_claiming_clear(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    _, review = service.apply(
        'set',
        {
            'tasks': [
                {
                    'id': 'external',
                    'description': 'Wait for unavailable credential',
                    'status': 'blocked',
                }
            ]
        },
    )

    assert 'RECORDED STATUS\nBLOCKED — external' in review
    assert 'RECORDED STATUS\nCLEAR' not in review


def test_satisfied_contract_and_completed_plan_render_clear(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    _, review = service.apply(
        'set',
        {
            'requirements': [
                {
                    'id': 'req',
                    'text': 'Requested behavior works',
                    'status': 'satisfied',
                }
            ],
            'tasks': [
                {'id': 'task', 'description': 'Implement behavior', 'status': 'done'}
            ],
        },
    )

    assert 'RECORDED STATUS\nCLEAR' in review
    assert 'no unresolved contract conditions or open tasks recorded' in review


def test_set_rejects_silently_ignored_contract_wrapper(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))

    with pytest.raises(ValueError, match='wrapper field.*contract'):
        service.apply(
            'set',
            {'contract': '{"objective": "Do the whole task"}', 'tasks': []},
        )


def test_set_rejects_invalid_contract_status(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))

    with pytest.raises(ValueError, match="Invalid contract status 'todo'"):
        service.apply(
            'set',
            {'requirements': [{'id': 'req', 'text': 'Finish', 'status': 'todo'}]},
        )
