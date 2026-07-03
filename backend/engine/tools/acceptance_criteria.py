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
    'Define flat verifiable acceptance criteria — what must be true when done. '
    'REQUIRED at the start of structured work (bugfix, implementation, refactor, multi-step tasks): '
    'call `update` with `criteria_list` before any file edit or shell command. '
    'Typical workflow: `update` (start) → implement + verify → `audit` (before final summary). '
    'Use `view` to read criteria. Use `append` for rare missing items. '
    'Use `audit` before the final summary to record evidence or explicit gaps on every item. '
    'Phrase criteria as auditable assertions, not activities.'
)

_CRITERION_ITEM_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
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
                'Optional. Set only during `audit`: file/test/output proving the assertion, '
                'or an explicit gap (e.g. "GAP: not implemented").'
            ),
        },
    },
    'required': ['assertion', 'source'],
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
                '`append` adds items. `audit` records evidence/gaps on every item.',
                ['view', 'update', 'append', 'audit'],
            ),
            'criteria_list': {
                'type': 'array',
                'description': (
                    'Flat list of acceptance criteria. Required for `update`, `append`, and `audit`. '
                    'For `update`, include every criterion. For `append`, include only new items. '
                    'For `audit`, include every criterion with `evidence` filled.'
                ),
                'items': _CRITERION_ITEM_SCHEMA,
            },
        },
        required=['command'],
    )


__all__ = ['create_acceptance_criteria_tool']
