"""Flat acceptance criteria tool definition for Orchestrator runs."""

from typing import Any

from backend.core.criteria.criterion_item import (
    CRITERION_SOURCE_INFERRED,
    CRITERION_SOURCE_STATED,
)
from backend.core.tools.tool_names import ACCEPTANCE_CRITERIA_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition, get_command_param

_ACCEPTANCE_CRITERIA_DESCRIPTION = (
    'Verifiable done-conditions (what must be true). See `<ACCEPTANCE_CRITERIA>`. '
    'Commands: `view`, `update`, `append`, `refine`, `audit` (before final summary).'
)

_CRITERION_ITEM_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'id': {
            'type': 'string',
            'description': (
                'Stable criterion id (e.g. ac1). Assigned automatically on write; '
                'include on update/append when preserving existing items.'
            ),
        },
        'assertion': {
            'type': 'string',
            'description': (
                'Terse verifiable assertion (e.g. "Const assignment raises TypeError 409").'
            ),
        },
        'source': {
            'type': 'string',
            'description': 'Whether the user stated this or you inferred it.',
            'enum': [CRITERION_SOURCE_STATED, CRITERION_SOURCE_INFERRED],
        },
        'evidence': {
            'type': 'string',
            'description': (
                'Audit evidence or explicit gap (e.g. "pytest: 42 passed"). '
                'Prefer `audit_entries` with `evidence` on each criterion.'
            ),
        },
    },
    'required': ['assertion', 'source'],
    'additionalProperties': False,
}

_AUDIT_ENTRY_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'criterion_id': {
            'type': 'string',
            'description': 'Stable id of the criterion being audited (from `view`).',
        },
        'evidence': {
            'type': 'string',
            'description': (
                'Free-text evidence or explicit gap (e.g. "pytest: 42 passed, 1 skipped" '
                'or "GAP: not implemented"). Quote the relevant command output or observation.'
            ),
        },
    },
    'required': ['criterion_id', 'evidence'],
    'additionalProperties': False,
}


def create_acceptance_criteria_tool() -> ChatCompletionToolParam:
    """Create the acceptance criteria tool for the Orchestrator agent."""
    return create_tool_definition(
        name=ACCEPTANCE_CRITERIA_TOOL_NAME,
        description=_ACCEPTANCE_CRITERIA_DESCRIPTION,
        properties={
            'command': get_command_param(
                'The command to execute. `view` shows criteria. `update` replaces the full list. '
                '`append` adds items. `refine` updates one assertion in place. '
                '`audit` records evidence on every item via `audit_entries`.',
                ['view', 'update', 'append', 'refine', 'audit'],
            ),
            'criteria_list': {
                'type': 'array',
                'description': (
                    'Flat list of acceptance criteria. Required for `update` and `append`. '
                    'For `update`, include every criterion. For `append`, include only new items. '
                    'Legacy `audit` accepts every criterion with `evidence` filled; prefer `audit_entries`.'
                ),
                'items': _CRITERION_ITEM_SCHEMA,
            },
            'criterion_id': {
                'type': 'string',
                'description': 'Target criterion id for `refine` (from `view`).',
            },
            'new_assertion': {
                'type': 'string',
                'description': 'Updated assertion text for `refine`.',
            },
            'reason': {
                'type': 'string',
                'description': (
                    'Non-empty explanation of why the assertion changed. Required for `refine`.'
                ),
            },
            'audit_entries': {
                'type': 'array',
                'description': (
                    'Per-criterion audit records. Required for `audit` (preferred over legacy '
                    '`criteria_list` evidence). Every current criterion must appear once.'
                ),
                'items': _AUDIT_ENTRY_SCHEMA,
            },
        },
        required=['command'],
    )


__all__ = ['create_acceptance_criteria_tool']
