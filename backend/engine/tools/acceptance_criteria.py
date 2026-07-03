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
    'Use `view` to read criteria (includes stable `id` on each item). Use `append` for rare missing items. '
    'Use `refine` to correct an existing assertion in place (requires `reason`). '
    'Use `audit` before the final summary to attach verbatim tool output via `evidence_ref`. '
    'Phrase criteria as auditable assertions, not activities.'
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
                'Legacy audit field: free-text evidence or gap. Prefer `audit_entries` with '
                '`evidence_ref` for objective checks; use free-text only with `unverifiable: true`.'
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
        'evidence_ref': {
            'type': 'string',
            'description': (
                'Reference to prior tool output in this session, e.g. '
                '"call_abc123:lines[10-25]" or "event:847:lines[1-5]". '
                'Resolved verbatim at audit time — do not paraphrase.'
            ),
        },
        'evidence': {
            'type': 'string',
            'description': (
                'Free-text evidence or explicit gap (e.g. "GAP: not implemented"). '
                'Only for subjective/unverifiable criteria when paired with `unverifiable: true`.'
            ),
        },
        'unverifiable': {
            'type': 'boolean',
            'description': (
                'Required true when using free-text `evidence` instead of `evidence_ref`.'
            ),
        },
    },
    'required': ['criterion_id'],
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
