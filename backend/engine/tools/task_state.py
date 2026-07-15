"""Single model-facing tool for durable contract and plan state."""

from typing import Any

from backend.core.tools.tool_names import TASK_STATE_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition, get_command_param


def create_task_state_tool() -> ChatCompletionToolParam:
    contract_item: dict[str, Any] = {
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},
            'text': {'type': 'string'},
            'source': {
                'type': 'string',
                'enum': ['user', 'repository', 'system', 'agent'],
            },
            'status': {
                'type': 'string',
                'enum': ['unknown', 'satisfied', 'gap', 'not_applicable'],
            },
        },
        'required': ['text'],
        'additionalProperties': False,
    }
    task: dict[str, Any] = {
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},
            'description': {'type': 'string'},
            'status': {
                'type': 'string',
                'enum': ['todo', 'in_progress', 'done', 'skipped', 'blocked'],
            },
            'result': {'type': 'string'},
        },
        'required': ['id', 'description'],
        'additionalProperties': False,
    }
    evidence: dict[str, Any] = {
        'type': 'object',
        'properties': {
            'item_id': {'type': 'string'},
            'status': {
                'type': 'string',
                'enum': ['unknown', 'satisfied', 'gap', 'not_applicable'],
            },
            'evidence': {'type': 'string'},
            'kind': {'type': 'string'},
        },
        'required': ['item_id', 'status', 'evidence'],
        'additionalProperties': False,
    }
    return create_tool_definition(
        name=TASK_STATE_TOOL_NAME,
        description=(
            'Create and maintain durable state for substantial multi-step work. '
            'The contract records the overall user objective and what must remain '
            'true; tasks record the current strategy. For set, pass objective, '
            'requirements, constraints, success_conditions, and tasks directly as '
            'top-level structured arguments. Do not use contract/plan wrappers and '
            'do not JSON-encode fields. Use review to refresh the full state and audit '
            'to attach evidence. This tool reports state; it does not decide whether '
            'you should finish.'
        ),
        properties={
            'action': get_command_param(
                'set updates supplied top-level contract/plan fields; update_task '
                'changes one task; review is read-only; audit records contract evidence.',
                ['set', 'update_task', 'review', 'audit'],
            ),
            'expected_revision': {'type': 'integer'},
            'objective': {'type': 'string'},
            'requirements': {'type': 'array', 'items': contract_item},
            'constraints': {'type': 'array', 'items': contract_item},
            'success_conditions': {'type': 'array', 'items': contract_item},
            'tasks': {'type': 'array', 'items': task},
            'task_id': {'type': 'string'},
            'status': {
                'type': 'string',
                'enum': ['todo', 'in_progress', 'done', 'skipped', 'blocked'],
            },
            'result': {'type': 'string'},
            'evidence': {'type': 'array', 'items': evidence},
        },
        required=['action'],
    )


__all__ = ['create_task_state_tool']
