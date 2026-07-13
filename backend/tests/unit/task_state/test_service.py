from backend.task_state.service import TaskStateService
from backend.task_state.store import TaskStateStore


def test_set_preserves_unsupplied_contract_fields(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    state, _ = service.apply('set', {'objective': 'Ship it', 'requirements': [{'id': 'req-1', 'text': 'Keep API', 'source': 'user'}]})
    state, _ = service.apply('set', {'tasks': [{'id': 'task-1', 'description': 'Inspect'}], 'expected_revision': state.revision})
    assert state.contract is not None
    assert state.contract.requirements[0].text == 'Keep API'
    assert state.plan is not None


def test_audit_records_structured_evidence(tmp_path):
    service = TaskStateService(TaskStateStore(tmp_path))
    service.apply('set', {'requirements': [{'id': 'req-1', 'text': 'Tests pass'}]})
    state, _ = service.apply('audit', {'evidence': [{'item_id': 'req-1', 'status': 'satisfied', 'kind': 'test', 'evidence': '12 passed'}]})
    item = state.contract.requirements[0]
    assert item.status == 'satisfied'
    assert item.evidence[0].kind == 'test'
