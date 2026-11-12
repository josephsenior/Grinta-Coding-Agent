"""Deterministically project execution-evidence JSONL records."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def _blank() -> dict[str, Any]:
    return {
        'schema_version': 1,
        'run': {
            'duration_ms': None,
            'final_agent_state': None,
            'additional_user_inputs': None,
        },
        'model': {
            'turns': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'reasoning_tokens': 0,
            'cache_read_tokens': 0,
            'cache_write_tokens': 0,
            'cost_usd': 0.0,
        },
        'tools': {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'blocked': 0,
            'by_tool': {},
        },
        'verification_activity': {'test_runs': 0, 'last_test_exit_code': None},
        'workspace': {'files_read': [], 'files_changed': []},
        'reliability': {
            'control_interventions': 0,
            'retries': 0,
            'recoveries': 0,
            'stuck_detections': 0,
            'circuit_breaker_triggers': 0,
            'context_compactions': 0,
            'checkpoints_created': 0,
            'restores': 0,
        },
        'completion': {
            'finish_declared': False,
            'task_recorded_status': None,
            'completion_validator': None,
        },
        'contract': {
            'total_criteria': 0,
            'criteria_with_linked_evidence': 0,
            'criteria_without_linked_evidence': 0,
            'status_counts': {},
        },
    }


def _records(source: Path | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(source, Path):
        return [row for row in source if isinstance(row, dict)]
    result: list[dict[str, Any]] = []
    try:
        lines = source.read_text(encoding='utf-8').splitlines()
    except OSError:
        return result
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            result.append(row)
    return result


def _accepted_payload(row: dict[str, Any], seen: set[str]) -> dict[str, Any] | None:
    payload = row.get('payload')
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        return None
    evidence_id = payload.get('evidence_id')
    if not isinstance(evidence_id, str) or evidence_id in seen:
        return None
    seen.add(evidence_id)
    data = payload.get('data')
    if not isinstance(data, dict):
        return None
    return payload


def _record_timestamp(timestamps: list[datetime], row: dict[str, Any]) -> None:
    try:
        timestamps.append(
            datetime.fromisoformat(str(row.get('ts')).replace('Z', '+00:00'))
        )
    except ValueError:
        pass


def _project_checkpoint(summary: dict[str, Any], data: dict[str, Any]) -> None:
    operation = data.get('operation')
    if operation == 'create':
        summary['reliability']['checkpoints_created'] += 1
    if operation == 'restore':
        summary['reliability']['restores'] += 1


def _project_finish(summary: dict[str, Any], data: dict[str, Any]) -> None:
    summary['completion']['finish_declared'] = True
    summary['completion']['task_recorded_status'] = data.get('recorded_task_status')
    summary['run']['final_agent_state'] = 'FINISHED'


def _project_payload(
    summary: dict[str, Any],
    payload: dict[str, Any],
    tools: Counter[str],
    files_read: set[str],
    files_changed: set[str],
) -> int:
    kind = payload.get('kind')
    data = payload['data']
    if kind == 'model_turn':
        _project_model(summary, data)
    elif kind == 'tool_execution':
        _project_tool(summary, data, tools, files_read, files_changed)
    elif kind == 'user_input':
        return 1
    elif kind == 'control_intervention':
        _project_intervention(summary, data)
    elif kind == 'context_compaction':
        summary['reliability']['context_compactions'] += 1
    elif kind == 'checkpoint':
        _project_checkpoint(summary, data)
    elif kind == 'finish_declared':
        _project_finish(summary, data)
    elif kind == 'completion_validation':
        summary['completion']['completion_validator'] = data
    return 0


def project(
    source: Path | Iterable[dict[str, Any]], task_state: dict[str, Any] | None = None
) -> dict[str, Any]:
    summary = _blank()
    seen: set[str] = set()
    timestamps: list[datetime] = []
    tools: Counter[str] = Counter()
    files_read: set[str] = set()
    files_changed: set[str] = set()
    user_inputs = 0
    for row in _records(source):
        if row.get('event') != 'EXECUTION_EVIDENCE':
            continue
        payload = _accepted_payload(row, seen)
        if payload is None:
            continue
        _record_timestamp(timestamps, row)
        user_inputs += _project_payload(
            summary, payload, tools, files_read, files_changed
        )
    summary['tools']['by_tool'] = dict(sorted(tools.items()))
    summary['workspace']['files_read'] = sorted(files_read)
    summary['workspace']['files_changed'] = sorted(files_changed)
    summary['run']['additional_user_inputs'] = (
        max(0, user_inputs - 1) if user_inputs else 0
    )
    if len(timestamps) >= 2:
        summary['run']['duration_ms'] = int(
            (max(timestamps) - min(timestamps)).total_seconds() * 1000
        )
    _project_contract(summary, task_state)
    return summary


def _project_model(summary: dict[str, Any], data: dict[str, Any]) -> None:
    model = summary['model']
    model['turns'] += 1
    for key in (
        'prompt_tokens',
        'completion_tokens',
        'reasoning_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
    ):
        model[key] += int(data.get(key, 0) or 0)
    model['cost_usd'] += float(data.get('cost_usd', 0) or 0)


def _project_tool(
    summary: dict[str, Any],
    data: dict[str, Any],
    tools: Counter[str],
    files_read: set[str],
    files_changed: set[str],
) -> None:
    tools[data.get('tool') or '<unknown>'] += 1
    summary['tools']['total'] += 1
    outcome = str(data.get('outcome') or '')
    if outcome == 'success':
        summary['tools']['successful'] += 1
    elif outcome.startswith('blocked'):
        summary['tools']['blocked'] += 1
    else:
        summary['tools']['failed'] += 1
    if data.get('verification_kind') == 'test':
        summary['verification_activity']['test_runs'] += 1
        summary['verification_activity']['last_test_exit_code'] = data.get('exit_code')
    files_read.update(
        value for value in data.get('read_paths', []) if isinstance(value, str)
    )
    files_changed.update(
        value for value in data.get('changed_paths', []) if isinstance(value, str)
    )


def _project_intervention(summary: dict[str, Any], data: dict[str, Any]) -> None:
    reliability = summary['reliability']
    reliability['control_interventions'] += 1
    intervention = str(data.get('intervention') or '')
    if 'retry' in intervention:
        reliability['retries'] += 1
    if 'recover' in intervention:
        reliability['recoveries'] += 1
    if intervention == 'stuck_detected':
        reliability['stuck_detections'] += 1
    if intervention == 'circuit_breaker_triggered':
        reliability['circuit_breaker_triggers'] += 1


def _project_contract(
    summary: dict[str, Any], task_state: dict[str, Any] | None
) -> None:
    if not isinstance(task_state, dict):
        return
    contract = task_state.get('contract') or {}
    items = [
        row
        for group in ('requirements', 'constraints', 'success_conditions')
        for row in contract.get(group, [])
        if isinstance(row, dict)
    ]
    linked = sum(
        bool(row.get('evidence'))
        and any(
            item.get('source_event_ids')
            for item in row.get('evidence', [])
            if isinstance(item, dict)
        )
        for row in items
    )
    summary['contract']['total_criteria'] = len(items)
    summary['contract']['criteria_with_linked_evidence'] = linked
    summary['contract']['criteria_without_linked_evidence'] = len(items) - linked
    summary['contract']['status_counts'] = dict(
        Counter(str(row.get('status', 'unknown')) for row in items)
    )
